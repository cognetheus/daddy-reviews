/*
 * R7.04 Java semantic references via the JDK javac Tree API (JDK 17+).
 * Inputs are bounded staged snapshot files supplied by the Python wrapper.
 * Never invoke project code, annotation processors, Maven or Gradle.
 */
import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.lang.model.element.*;
import javax.tools.*;
import java.io.File;
import java.nio.file.*;
import java.util.*;
import java.util.stream.Collectors;

public final class JavaSymbolIndex {
  static final class Ref {
    String path, relationship;
    long line;
    Ref(String p, long l, String r) { path = p; line = l; relationship = r; }
  }
  static String json(String s) {
    if (s == null) return "null";
    StringBuilder b = new StringBuilder("\"");
    for (int i=0; i<s.length(); i++) {
      char c=s.charAt(i);
      switch (c) {
        case '"': b.append("\\\""); break;
        case '\\': b.append("\\\\"); break;
        case '\n': b.append("\\n"); break;
        case '\r': b.append("\\r"); break;
        case '\t': b.append("\\t"); break;
        default: if (c < 32) b.append(String.format("\\u%04x", (int)c));
                 else b.append(c);
      }
    }
    return b.append('"').toString();
  }
  static void output(String status, String version, String targetPath, long definition,
                     List<Ref> refs, List<String> warnings) {
    StringBuilder s = new StringBuilder("{\"format\":\"daddy-reviews-javac-v1\",");
    s.append("\"status\":").append(json(status)).append(",\"compiler_version\":").append(json(version));
    s.append(",\"definition\":");
    if (definition < 1) s.append("null");
    else s.append("{\"path\":").append(json(targetPath)).append(",\"line\":").append(definition).append("}");
    s.append(",\"references\":[");
    for (int i=0; i<refs.size(); i++) {
      if (i>0) s.append(",");
      Ref r=refs.get(i);
      s.append("{\"path\":").append(json(r.path)).append(",\"line\":").append(r.line)
       .append(",\"relationship\":").append(json(r.relationship)).append("}");
    }
    s.append("],\"warnings\":[");
    for (int i=0; i<warnings.size(); i++) {
      if (i>0) s.append(",");
      s.append(json(warnings.get(i)));
    }
    System.out.println(s.append("]}"));
  }

  public static void main(String[] args) {
    List<String> warnings = new ArrayList<>();
    List<Ref> refs = new ArrayList<>();
    String version = System.getProperty("java.specification.version");
    String targetPath = args.length>1 ? args[1] : "";
    if (args.length < 4) { output("invalid", version, targetPath, 0, refs, List.of("Arguments required")); return; }
    try { run(args, version, warnings, refs); }
    catch (Exception ex) {
      output("incomplete", version, targetPath, 0, List.of(), List.of("Java compiler adapter failed: " + ex.getClass().getSimpleName()));
    }
  }
  static void run(String[] args, String version, List<String> warnings, List<Ref> refs) throws Exception {
    Path root=Paths.get(args[0]).toRealPath();
    String targetPath=args[1], symbol=args[2];
    if (!targetPath.endsWith(".java") || targetPath.contains("..") ||
        !symbol.matches("[A-Za-z_$][\\w$]*(\\.[A-Za-z_$][\\w$]*)?")) {
      output("invalid", version, targetPath, 0, refs, List.of("Invalid target")); return;
    }
    List<File> inputs=new ArrayList<>();
    HashMap<String,String> normalized=new HashMap<>();
    for (int i=3; i<args.length; i++) {
      Path file=root.resolve(args[i]).normalize();
      if (!file.startsWith(root) || !file.toString().endsWith(".java") || !Files.isRegularFile(file) ||
          Files.isSymbolicLink(file) || normalized.containsKey(file.toString())) {
        output("invalid", version, targetPath, 0, refs, List.of("Unsafe or duplicate source")); return;
      }
      inputs.add(file.toFile());
      normalized.put(file.toString(), args[i].replace('\\','/'));
    }
    if (inputs.size() > 800) { output("incomplete",version,targetPath,0,refs,List.of("File budget exceeded")); return; }
    JavaCompiler compiler=ToolProvider.getSystemJavaCompiler();
    if (compiler==null) { output("unavailable",version,targetPath,0,refs,List.of("JDK compiler not found")); return; }
    DiagnosticCollector<JavaFileObject> diags=new DiagnosticCollector<>();
    try(StandardJavaFileManager fm=compiler.getStandardFileManager(diags,Locale.ROOT,java.nio.charset.StandardCharsets.UTF_8)) {
      Iterable<? extends JavaFileObject> files=fm.getJavaFileObjectsFromFiles(inputs);
      List<String> options=List.of("-proc:none", "-implicit:none", "-classpath", root.toString(),
                                   "-sourcepath", root.toString(), "--release", "17", "-Xlint:none");
      JavacTask task=(JavacTask)compiler.getTask(null,fm,diags,options,null,files);
      List<CompilationUnitTree> units=new ArrayList<>();
      for (CompilationUnitTree unit:task.parse()) units.add(unit);
      task.analyze();
      Trees trees=Trees.instance(task);
      String[] segs=symbol.split("\\.");
      List<Element> targets=new ArrayList<>();
      List<Long> targetLines=new ArrayList<>();
      for(CompilationUnitTree unit:units) {
        String rel=normalized.get(Paths.get(unit.getSourceFile().toUri()).toString());
        if (!targetPath.equals(rel)) continue;
        new TreePathScanner<Void,Void>() {
          String owner="";
          @Override public Void visitClass(ClassTree node,Void unused) {
            String prev=owner;owner=node.getSimpleName().toString();
            if (segs.length==1 && owner.equals(segs[0])) {
              Element element=trees.getElement(getCurrentPath());
              if(element!=null){ targets.add(element);targetLines.add(unit.getLineMap().getLineNumber(trees.getSourcePositions().getStartPosition(unit,node))); }
            }
            super.visitClass(node,unused); owner=prev;return null;
          }
          @Override public Void visitMethod(MethodTree node,Void unused) {
            if(segs.length==2 && owner.equals(segs[0]) && node.getName().contentEquals(segs[1])) {
              Element el=trees.getElement(getCurrentPath());
              if(el!=null){ targets.add(el);targetLines.add(unit.getLineMap().getLineNumber(trees.getSourcePositions().getStartPosition(unit,node))); }
            }
            return super.visitMethod(node,unused);
          }
        }.scan(unit,null);
      }
      if(targets.size()!=1) {
        output(targets.isEmpty()?"unresolved":"ambiguous",version,targetPath,0,refs,
               List.of("Target declaration not uniquely resolved"));return;
      }
      Element target=targets.get(0);
      long def=targetLines.get(0);
      Set<String> seen=new HashSet<>();
      for(CompilationUnitTree unit:units) {
        String rel=normalized.get(Paths.get(unit.getSourceFile().toUri()).toString());
        if(rel==null || rel.equals(targetPath)) continue;
        new TreePathScanner<Void,Void>() {
          void add(TreePath path, Tree node, String relationship, Element el) {
            if(el==null) return;
            boolean match=el.equals(target);
            if (!match && target instanceof TypeElement && el instanceof ExecutableElement)
              match=el.getEnclosingElement().equals(target);
            if(!match) return;
            long at=trees.getSourcePositions().getStartPosition(unit,node);
            if(at < 0) return;
            long line=unit.getLineMap().getLineNumber(at);
            if(line<1 || refs.size()>=500) return;
            String key=rel+":"+line+":"+relationship;
            if(seen.add(key)) refs.add(new Ref(rel,line,relationship));
          }
          @Override public Void visitMethodInvocation(MethodInvocationTree node,Void v) {
            TreePath selected = new TreePath(getCurrentPath(),node.getMethodSelect());
            add(selected,node,"method_call",trees.getElement(selected));
            return super.visitMethodInvocation(node,v);
          }
          @Override public Void visitNewClass(NewClassTree node,Void v) {
            add(getCurrentPath(),node,"constructor_call",trees.getElement(getCurrentPath()));
            return super.visitNewClass(node,v);
          }
          @Override public Void visitIdentifier(IdentifierTree node,Void v) {
            Element el=trees.getElement(getCurrentPath());
            if(el!=null && (el.getKind().isClass()||el.getKind().isInterface())) {
              add(getCurrentPath(),node,"type_reference",el);
            }
            return super.visitIdentifier(node,v);
          }
        }.scan(unit,null);
      }
      refs.sort(Comparator.comparing((Ref r)->r.path).thenComparingLong(r->r.line).thenComparing(r->r.relationship));
      long errors=diags.getDiagnostics().stream().filter(d->d.getKind()==Diagnostic.Kind.ERROR).count();
      if(errors>0) warnings.add("Javac reported "+errors+" unresolved/error diagnostic(s); coverage is partial");
      if(refs.size()>=500) warnings.add("Reference budget reached; coverage is partial");
      output(warnings.isEmpty()?"complete":"partial",version,targetPath,def,refs,warnings);
    }
  }
}
