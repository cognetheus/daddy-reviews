// R7.04: Roslyn semantic symbols from Python-verified read-only source snapshots.
// Standalone C# compilation: no reviewed project MSBuild hooks, generators,
// analyzers, or arbitrary external NuGet package execution.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

record LocationRef(string path, int line, string relationship);
record LocationDef(string path, int line);

internal static class Program
{
    static void Emit(string status, string version, LocationDef? definition,
                     IEnumerable<LocationRef> references, IEnumerable<string> warnings)
    {
        Console.WriteLine(JsonSerializer.Serialize(new {
            format="daddy-reviews-roslyn-v1", status, compiler_version=version,
            definition, references, warnings
        },new JsonSerializerOptions {PropertyNamingPolicy=JsonNamingPolicy.CamelCase}));
    }

    static bool SafeName(string name) =>
        !string.IsNullOrEmpty(name) && name.Length<=1024 && name.EndsWith(".cs") &&
        !name.Contains('\\') && !name.Contains('\0') && !name.StartsWith('/') &&
        name.Split('/').All(s=>s.Length>0 && s!="." && s!="..");

    static bool Equal(ISymbol? a, ISymbol? b)
    {
        if(a is null || b is null)return false;
        return SymbolEqualityComparer.Default.Equals(a.OriginalDefinition,b.OriginalDefinition);
    }

    static int Main(string[] args)
    {
        var version=typeof(CSharpCompilation).Assembly.GetName().Version?.ToString() ?? "unknown";
        if (args.Length<4 || !Path.IsPathFullyQualified(args[0]) ||
            !SafeName(args[1]) || string.IsNullOrEmpty(args[2]) ||
            args[2].Split('.').Length>2 ||
            args[2].Split('.').Any(s=>s.Length==0 || !char.IsLetter(s[0]) ||
                s.Any(c=>!(char.IsLetterOrDigit(c)||c=='_'))))
        {
            Emit("invalid",version,null,Array.Empty<LocationRef>(),new[]{"Invalid request"});
            return 0;
        }
        try { Execute(args,version); }
        catch(Exception e)
        {
            Emit("incomplete",version,null,Array.Empty<LocationRef>(),new[]{
                "Roslyn adapter failed: "+e.GetType().Name
            });
        }
        return 0;
    }

    static void Execute(string[] args,string version)
    {
        var root=Path.GetFullPath(args[0]);
        var requested=args[1];
        var symbol=args[2];
        var sourcePaths=new Dictionary<string,string>(StringComparer.Ordinal);
        var trees=new List<SyntaxTree>();
        foreach(var rel in args.Skip(3))
        {
            if(!SafeName(rel))
            {
                Emit("invalid",version,null,Array.Empty<LocationRef>(),new[]{"Invalid source path"});
                return;
            }
            var file=Path.GetFullPath(Path.Combine(root,rel));
            if(!file.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.Ordinal) ||
               sourcePaths.ContainsKey(file) || !File.Exists(file) ||
               (File.GetAttributes(file) & FileAttributes.ReparsePoint)!=0)
            {
                Emit("invalid",version,null,Array.Empty<LocationRef>(),new[]{"Unsafe source"});
                return;
            }
            sourcePaths[file]=rel.Replace('\\','/');
            trees.Add(CSharpSyntaxTree.ParseText(File.ReadAllText(file),path:file));
        }
        if(trees.Count>800)
        {
            Emit("incomplete",version,null,Array.Empty<LocationRef>(),new[]{"File budget"});
            return;
        }
        if(!sourcePaths.Values.Contains(requested))
        {
            Emit("unresolved",version,null,Array.Empty<LocationRef>(),new[]{"Missing target"});
            return;
        }
        var assemblies=(AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string ?? "")
            .Split(Path.PathSeparator,StringSplitOptions.RemoveEmptyEntries)
            .Where(File.Exists).Select(x=>MetadataReference.CreateFromFile(x)).ToList();
        if(assemblies.Count==0) assemblies.Add(MetadataReference.CreateFromFile(typeof(object).Assembly.Location));
        var compilation=CSharpCompilation.Create("DaddyReviewsSemanticOnly",trees,assemblies,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary,
                nullableContextOptions:NullableContextOptions.Enable));
        var names=symbol.Split('.');
        var found=new List<(ISymbol s, LocationDef def)>();
        foreach(var tree in trees)
        {
            if(!sourcePaths.TryGetValue(tree.FilePath,out var rel) || rel!=requested) continue;
            var model=compilation.GetSemanticModel(tree);
            var syntax=tree.GetRoot();
            foreach(var cl in syntax.DescendantNodes().OfType<BaseTypeDeclarationSyntax>())
            {
                if(names[0]!=cl.Identifier.Text)continue;
                if(names.Length==1)
                {
                    var named=model.GetDeclaredSymbol(cl);
                    if(named is not null)found.Add((named,new LocationDef(rel,cl.GetLocation().GetLineSpan().StartLinePosition.Line+1)));
                }
                if(names.Length==2 && cl is TypeDeclarationSyntax typeDecl)
                {
                    foreach(var method in typeDecl.Members.OfType<MethodDeclarationSyntax>().Where(x=>x.Identifier.Text==names[1]))
                    {
                        var m=model.GetDeclaredSymbol(method);
                        if(m is not null)found.Add((m,new LocationDef(rel,method.GetLocation().GetLineSpan().StartLinePosition.Line+1)));
                    }
                }
            }
        }
        if(found.Count!=1)
        {
            Emit(found.Count==0?"unresolved":"ambiguous",version,null,Array.Empty<LocationRef>(),
                new[]{"Target declaration not uniquely resolved"});
            return;
        }
        var selected=found[0].s;
        var results=new List<LocationRef>();
        var keys=new HashSet<string>();
        foreach(var tree in trees)
        {
            if(!sourcePaths.TryGetValue(tree.FilePath,out var rel) || rel==requested) continue;
            var model=compilation.GetSemanticModel(tree);
            foreach(var syntax in tree.GetRoot().DescendantNodes())
            {
                ISymbol? resolved=null;
                string? relationship=null;
                switch (syntax)
                {
                    case InvocationExpressionSyntax call:
                        resolved=model.GetSymbolInfo(call).Symbol;
                        relationship="method_call";
                        break;
                    case ObjectCreationExpressionSyntax creation:
                        resolved=model.GetSymbolInfo(creation).Symbol;
                        relationship="constructor_call";
                        if(selected is INamedTypeSymbol && resolved is IMethodSymbol ctor)
                            resolved=ctor.ContainingType;
                        break;
                    case ImplicitObjectCreationExpressionSyntax implicitNew:
                        resolved=model.GetSymbolInfo(implicitNew).Symbol;
                        relationship="constructor_call";
                        if(selected is INamedTypeSymbol && resolved is IMethodSymbol ctor2)
                            resolved=ctor2.ContainingType;
                        break;
                    case TypeSyntax typeNode when selected is INamedTypeSymbol &&
                        syntax.Parent is not (ObjectCreationExpressionSyntax or MemberAccessExpressionSyntax):
                        resolved=model.GetSymbolInfo(typeNode).Symbol ?? model.GetTypeInfo(typeNode).Type;
                        relationship="type_reference";
                        break;
                }
                if(relationship is null || !Equal(resolved,selected))continue;
                int line=syntax.GetLocation().GetLineSpan().StartLinePosition.Line+1;
                if(line<1 || results.Count>=500)continue;
                var key=rel+":"+line+":"+relationship;
                if(keys.Add(key))results.Add(new LocationRef(rel,line,relationship));
            }
        }
        results=results.OrderBy(x=>x.path,StringComparer.Ordinal).ThenBy(x=>x.line)
            .ThenBy(x=>x.relationship,StringComparer.Ordinal).ToList();
        var errs=compilation.GetDiagnostics().Count(x=>x.Severity==DiagnosticSeverity.Error);
        var warnings=new List<string>();
        if(errs>0)warnings.Add($"Roslyn reported {errs} error diagnostic(s); coverage is partial");
        if(results.Count>=500)warnings.Add("Reference budget reached; coverage is partial");
        Emit(warnings.Count==0?"complete":"partial",version,found[0].def,results,warnings);
    }
}
