using System.IO.Compression;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer.Game.PeerInput;
namespace OvernightHarness;
public static class DecisionSnapshots
{
    public static bool CaptureEnabled=>Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_CAPTURE")=="1";
    static readonly JsonSerializerOptions Json=new(){IncludeFields=true};
    public sealed class Envelope {
        public int Schema {get;set;}=1;
        public string DecisionId {get;set;}="";
        public bool CombatInProgress {get;set;}
        public string Kind {get;set;}="";
        public string GameAssemblyHash {get;set;}="";
        public string NativeState {get;set;}="";
        public JsonElement Observation {get;set;}
        public DecisionSnapshotGraph Graph {get;set;}=new();
    }
    public static Envelope Read(string file) {
        using var stream=File.OpenRead(file);using var zip=new GZipStream(stream,CompressionMode.Decompress);
        var envelope=JsonSerializer.Deserialize<Envelope>(zip,Json)!;
        if(envelope.Schema!=1)throw new InvalidDataException("Unsupported snapshot format");
        string hash=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(RunState).Assembly.Location)));
        if(hash!=envelope.GameAssemblyHash)throw new InvalidDataException("Snapshot game assembly differs");
        return envelope;
    }
    // Shared by SnapshotPlayback (read-only viewing) and SnapshotResume (hands
    // control back to the live decision loop). Restores the captured RunState and
    // installs it as the live RunManager/CombatManager state via the same
    // reflection path, then verifies the injected state matches what was captured
    // — this is the same round-trip check DecisionSnapshotGraph.Capture already
    // performs at capture time, re-run here against the actual live singletons
    // rather than a throwaway comparison object.
    public static RunState Inject(Envelope envelope) {
        var run=(RunState)envelope.Graph.Restore();
        var manager=RunManager.Instance;
        bool initialize=manager.DebugOnlyGetState()==null;
        AccessTools.Property(typeof(RunManager),"State").SetValue(manager,run);
        if(initialize) {
            var net=new NetSingleplayerGameService();
            AccessTools.Method(typeof(RunManager),"InitializeShared").Invoke(manager,new object?[]{net,new PeerInputSynchronizer(net),false,null,0L,0L,0L,0});
            AccessTools.Method(typeof(RunManager),"InitializeRunLobby").Invoke(manager,new object[]{net,run});
            MegaCrit.Sts2.Core.Context.LocalContext.NetId=net.NetId;
        }
        var combat=run.Players[0].Creature.CombatState;
        AccessTools.Field(typeof(CombatManager),"_state").SetValue(CombatManager.Instance,combat);
        AccessTools.Property(typeof(CombatManager),"IsInProgress").SetValue(CombatManager.Instance,envelope.CombatInProgress);
        string actual=JsonSerializer.Serialize(NetFullCombatState.FromRun(run,null),Json);
        if(Comparable(actual)!=Comparable(envelope.NativeState))throw new InvalidDataException("Injected snapshot differs from captured native state at "+envelope.DecisionId);
        return run;
    }
    public static string Comparable(string json) {
        var obj=System.Text.Json.Nodes.JsonNode.Parse(json)!.AsObject();
        foreach(string key in new[]{"nextChoiceIds","nextRewardIds","lastExecutedHookId","lastExecutedActionId"})obj.Remove(key);
        return obj.ToJsonString();
    }
    public static void Capture(string id,string kind,object observation)
    {
        if(!CaptureEnabled)return;
        var run=RunManager.Instance.DebugOnlyGetState()!;
        var graph=DecisionSnapshotGraph.Capture(run);
        graph.ExcludedRuntimeFields=graph.ExcludedRuntimeFields.Distinct().ToList();
        var bytes=JsonSerializer.SerializeToUtf8Bytes(graph,Json);
        var decoded=JsonSerializer.Deserialize<DecisionSnapshotGraph>(bytes,Json)!;
        RunState restored;
        try {restored=(RunState)decoded.Restore();}
        catch {
            File.WriteAllBytes(Path.Combine(Path.GetDirectoryName(Environment.GetEnvironmentVariable("DEALMAKER_TEST_LOG"))!,"snapshot-failed-"+id+".json"),bytes);
            throw;
        }
        string before=JsonSerializer.Serialize(NetFullCombatState.FromRun(run,null),Json);
        string after=JsonSerializer.Serialize(NetFullCombatState.FromRun(restored,null),Json);
        var originalMoves=run.Players[0].Creature.CombatState?.Enemies.Select(e=>e.Monster?.NextMove.Id).ToArray();
        var restoredMoves=restored.Players[0].Creature.CombatState?.Enemies.Select(e=>e.Monster?.NextMove.Id).ToArray();
        if(JsonSerializer.Serialize(originalMoves)!=JsonSerializer.Serialize(restoredMoves))throw new InvalidOperationException("Snapshot enemy move differs");
        var expectedRng=RunRngSet.FromSave(run.Rng.ToSerializable());
        foreach(var property in typeof(RunRngSet).GetProperties().Where(p=>p.PropertyType==typeof(MegaCrit.Sts2.Core.Random.Rng))) {
            var expected=(MegaCrit.Sts2.Core.Random.Rng)property.GetValue(expectedRng)!;
            var actual=(MegaCrit.Sts2.Core.Random.Rng)property.GetValue(restored.Rng)!;
            for(int sample=0;sample<3;sample++)if(expected.NextInt()!=actual.NextInt())throw new InvalidOperationException("Snapshot RNG stream differs: "+property.Name);
        }
        if(before!=after)throw new InvalidOperationException("Snapshot round-trip differs from native full combat state");
        string directory=Path.Combine(Path.GetDirectoryName(Environment.GetEnvironmentVariable("DEALMAKER_TEST_LOG"))!,"snapshots");Directory.CreateDirectory(directory);
        var envelope=new Envelope{DecisionId=id,Kind=kind,CombatInProgress=CombatManager.Instance.IsInProgress,Graph=graph,NativeState=before,Observation=JsonSerializer.SerializeToElement(observation),GameAssemblyHash=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(RunState).Assembly.Location)))};
        bytes=JsonSerializer.SerializeToUtf8Bytes(envelope,Json);
        using(var file=File.Create(Path.Combine(directory,id+".json.gz")))using(var zip=new GZipStream(file,CompressionLevel.Fastest))zip.Write(bytes);
        Harness.Log("snapshot_verified",new{id,kind,nodes=graph.Entries.Count,bytes=bytes.Length,excluded_runtime_fields=graph.ExcludedRuntimeFields.Count});
    }
}
