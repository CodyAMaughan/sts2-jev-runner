using System.Reflection;
using System.Collections;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Models;
namespace OvernightHarness;

// Version-locked logical-state graph. Native scene nodes and event subscriptions
// must be rebuilt by the presentation layer, never deserialized as live handles.
public sealed class DecisionSnapshotGraph
{
    public sealed class Value { public int? Ref {get;set;} public string? Type {get;set;} public string? Scalar {get;set;} }
    public sealed class Entry {
        public string Type {get;set;}=""; public string Kind {get;set;}="object";
        public Dictionary<string,Value> Fields {get;set;}=new(); public List<Value> Items {get;set;}=new();
        public int[]? Dimensions {get;set;}
        public string? MethodType {get;set;} public int MethodToken {get;set;} public string[]? MethodGenerics {get;set;} public Value? Target {get;set;}
    }
    public List<Entry> Entries {get;set;}=new(); public Value Root {get;set;}=new();
    public List<string> ExcludedRuntimeFields {get;set;}=new();
    static string Name(Type t)=>t.AssemblyQualifiedName!;
    static IEnumerable<FieldInfo> Fields(Type t) {
        for(Type? p=t;p!=null;p=p.BaseType)
            foreach(var f in p.GetFields(BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.DeclaredOnly))yield return f;
    }
    static string Key(FieldInfo f)=>f.DeclaringType!.FullName+"::"+f.Name;
    static bool Scalar(Type t)=>t.IsPrimitive||t.IsEnum||t==typeof(string)||t==typeof(decimal)||t==typeof(Guid)||t==typeof(DateTime)||t==typeof(DateTimeOffset)||t==typeof(TimeSpan);
    public static DecisionSnapshotGraph Capture(object root) {
        var graph=new DecisionSnapshotGraph();var seen=new Dictionary<object,int>(ReferenceEqualityComparer.Instance);
        Value Visit(object? o) {
            if(o==null)return new();var t=o.GetType();
            if(Scalar(t))return new(){Type=Name(t),Scalar=JsonSerializer.Serialize(o,t)};
            if(o is Type ty)return new(){Type="runtime-type",Scalar=Name(ty)};
            if(o is StringName sn)return new(){Type="string-name",Scalar=sn.ToString()};
            if(o is NodePath np)return new(){Type="node-path",Scalar=np.ToString()};
            if(o is GodotObject || o is Task || o is CancellationTokenSource)throw new NotSupportedException("Runtime object: "+t.FullName);
            if(seen.TryGetValue(o,out int old))return new(){Ref=old};
            int id=graph.Entries.Count;seen[o]=id;var e=new Entry{Type=Name(t)};graph.Entries.Add(e);
            if(o is AbstractModel model && !model.IsMutable)e.Kind="canonical";
            else if(o is IDictionary dictionary) {
                e.Kind="dictionary";e.Target=Visit(t.GetProperty("Comparer")?.GetValue(o));
                foreach(DictionaryEntry pair in dictionary){e.Items.Add(Visit(pair.Key));e.Items.Add(Visit(pair.Value));}
            } else if(t.IsGenericType && t.GetGenericTypeDefinition()==typeof(HashSet<>)) {
                e.Kind="set";e.Target=Visit(t.GetProperty("Comparer")?.GetValue(o));
                foreach(var item in (IEnumerable)o)e.Items.Add(Visit(item));
            }
            else if(o is Array array) {
                e.Dimensions=Enumerable.Range(0,array.Rank).Select(array.GetLength).ToArray();
                e.Kind="array";foreach(var item in array)e.Items.Add(Visit(item));
            } else if(o is Delegate del) {
                e.Kind="delegate";
                if(del.GetInvocationList().Length!=1)throw new NotSupportedException("Non-event multicast delegate "+t);
                e.MethodType=Name(del.Method.DeclaringType!);e.MethodToken=del.Method.MetadataToken;e.MethodGenerics=del.Method.IsGenericMethod?del.Method.GetGenericArguments().Select(Name).ToArray():null;e.Target=Visit(del.Target);
            } else {
                foreach(var f in Fields(t)) {
                    // Event delegates connect UI and service lifetimes. Gameplay
                    // delegates (e.g. enemy move functions) are retained above.
                    if(f.DeclaringType!.GetEvent(f.Name,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.DeclaredOnly)!=null) {
                        graph.ExcludedRuntimeFields.Add(Key(f));continue;
                    }
                    var val=f.GetValue(o);
                    if(val is GodotObject || val is Task || val is CancellationTokenSource) {
                        graph.ExcludedRuntimeFields.Add(Key(f));continue;
                    }
                    try {e.Fields[Key(f)]=Visit(val);}catch(Exception ex){throw new InvalidOperationException("Snapshot field "+Key(f),ex);}
                }
            }
            return new(){Ref=id};
        }
        graph.Root=Visit(root);return graph;
    }
    public object Restore() {
        var values=new object?[Entries.Count];var types=Entries.Select(e=>Type.GetType(e.Type,true)!).ToArray();
        for(int i=0;i<Entries.Count;i++) {
            var e=Entries[i];var t=types[i];
            values[i]=e.Kind switch {
                "canonical"=>typeof(ModelDb).GetMethod("Get",BindingFlags.Static|BindingFlags.NonPublic,null,new[]{typeof(Type)},null)!.Invoke(null,new object[]{t}),
                "array"=>Array.CreateInstance(t.GetElementType()!,e.Dimensions??new[]{e.Items.Count}),
                "delegate"=>null,
                "dictionary" or "set"=>Activator.CreateInstance(t),
                _=>RuntimeHelpers.GetUninitializedObject(t)
            };
        }
        var filled=new HashSet<int>();
        object? Read(Value v) {
            if(v.Ref is int id) {
                Fill(id);
                if(values[id]==null && Entries[id].Kind=="delegate") {
                    var e=Entries[id];var declaring=Type.GetType(e.MethodType!,true)!;
                    var method=declaring.GetMethods(BindingFlags.Instance|BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic).Single(m=>m.MetadataToken==e.MethodToken);
                    if(method.IsGenericMethodDefinition)method=method.MakeGenericMethod(e.MethodGenerics!.Select(n=>Type.GetType(n,true)!).ToArray());
                    try {values[id]=Delegate.CreateDelegate(types[id],Read(e.Target!),method);}
                    catch(Exception ex){throw new InvalidDataException("Snapshot delegate "+types[id]+" bound to "+method+" on "+declaring,ex);}
                }
                return values[id];
            }
            return v.Type switch {
                null=>null,"runtime-type"=>Type.GetType(v.Scalar!,true),"string-name"=>new StringName(v.Scalar!),"node-path"=>new NodePath(v.Scalar!),
                _=>JsonSerializer.Deserialize(v.Scalar!,Type.GetType(v.Type,true)!)
            };
        }
        void Fill(int i) {
            if(!filled.Add(i))return;
            var e=Entries[i];if(e.Kind is "canonical" or "delegate")return;
            if(e.Kind is "dictionary" or "set") {
                var comparer=Read(e.Target!);
                if(comparer!=null)types[i].GetField("_comparer",BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(values[i],comparer);
                if(values[i] is IDictionary dictionary)for(int j=0;j<e.Items.Count;j+=2)dictionary.Add(Read(e.Items[j])!,Read(e.Items[j+1]));
                else foreach(var v in e.Items)types[i].GetMethod("Add")!.Invoke(values[i],new[]{Read(v)});
            }
            else if(values[i] is Array a){for(int j=0;j<e.Items.Count;j++) {
                int rem=j;var indices=new int[a.Rank];for(int dim=a.Rank-1;dim>=0;dim--){indices[dim]=rem%a.GetLength(dim);rem/=a.GetLength(dim);}
                a.SetValue(Read(e.Items[j]),indices);
            }}
            else foreach(var f in Fields(types[i]))if(e.Fields.TryGetValue(Key(f),out var v))f.SetValue(values[i],Read(v));
        }
        return Read(Root)!;
    }
}
