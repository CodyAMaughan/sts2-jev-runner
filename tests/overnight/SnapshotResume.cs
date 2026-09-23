using HarmonyLib;
namespace OvernightHarness;

// Injects a captured full-run snapshot (see DecisionSnapshots/DecisionSnapshotGraph
// — round-trip verified against native combat state, enemy next-move IDs, and RNG
// stream determinism at capture time) and hands control to the SAME live decision
// loop a normal run uses, so real actions execute through the normal engine path —
// unlike SnapshotPlayback, which is deliberately read-only and shields live input.
//
// SCOPE TODAY: only a combat-kind snapshot can be resumed. RunAsync/PlayRunAsync's
// state machine is the single loop that sequences map -> combat -> rewards -> map
// for an entire run; replacing RunAsync (as this and SnapshotPlayback both do) skips
// that sequencing entirely; only the one directly-invoked step is real, and combat
// is the one step provably runnable without it, since RemotePilot.Combat only
// polls live CombatManager/RunManager state and never needs a Godot screen already
// on-screen. Whether the *next* room after combat ends is then driven by the
// engine's own Godot-side state reactions or needs PlayRunAsync's state machine
// re-entered explicitly is unverified — has not been run against the live engine.
// Non-combat snapshots (map/rewards/rest/shop/event) are refused outright: their
// screens are Godot scene objects RemoteScreens.Run reads live off ..Instance
// (e.g. NMapScreen.Instance), which SnapshotPlayback never reconstructs either —
// it falls back to a dead read-only text panel for those kinds today.
[HarmonyPatch(typeof(MegaCrit.Sts2.Core.AutoSlay.AutoSlayer),"RunAsync")]
static class SnapshotResume
{
    public static bool Enabled=>!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_RESUME"));
    [HarmonyPriority(Priority.First)]
    static bool Prefix(ref Task __result){if(!Enabled)return true;__result=Run();return false;}
    static async Task Run()
    {
        try
        {
            string path=Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_RESUME")!;
            var envelope=DecisionSnapshots.Read(path);
            var run=DecisionSnapshots.Inject(envelope);
            Harness.Log("snapshot_resume_injected",new{decision_id=envelope.DecisionId,kind=envelope.Kind,combat_in_progress=envelope.CombatInProgress});
            if(envelope.Kind!="combat"||!envelope.CombatInProgress)
                throw new NotSupportedException($"Resume is only implemented for a combat-in-progress snapshot; this one is kind={envelope.Kind}, combat_in_progress={envelope.CombatInProgress}. Its screen (map/rewards/rest/shop/event) is not reconstructed live yet — see SnapshotResume.cs.");
            await RemotePilot.Combat(CancellationToken.None);
            Harness.Log("snapshot_resume_combat_returned",new{decision_id=envelope.DecisionId,
                note="Combat loop returned (win or the harness's own death handling already quit the process on loss). Whether the engine naturally continues into the next room from here, or needs PlayRunAsync's state machine re-entered explicitly, is UNVERIFIED — resume has not been run against the live engine yet."});
        }
        catch(Exception e)
        {
            Harness.Log("snapshot_resume_failed",new{error=e.ToString()});
            throw;
        }
    }
}
