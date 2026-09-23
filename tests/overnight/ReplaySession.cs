using System.Reflection;
using Godot;
using Environment = System.Environment;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Saves;

namespace OvernightHarness;

// Replay-only restart boundary: unwind the current pilot, clean up the run, and
// enter the same seed again without destroying the native game window.
public sealed class ReplayResetException : Exception { }
[HarmonyPatch(typeof(AutoSlayer),"RunAsync")]
static class ReplaySession
{
    public static bool Enabled => !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DEALMAKER_REPLAY_CONTROLS"));
    static bool Prefix(AutoSlayer __instance,string seed,CancellationToken ct,ref Task __result)
    {
        if(!Enabled)return true;
        __result=Run(__instance,seed,ct);return false;
    }
    static async Task Run(AutoSlayer pilot,string seed,CancellationToken ct)
    {
        try {
            while(true) {
                try {
                    await (Task)AccessTools.Method(typeof(AutoSlayer),"PlayRunAsync").Invoke(pilot,new object[]{seed,ct})!;
                    break;
                } catch(Exception) when(DecisionBridge.ResetRequested) {
                    Harness.Log("replay_reset",new {pid=Environment.ProcessId,seed});
                    DisposeSelector(pilot);
                    if(SaveManager.Instance.CurrentRunSaveTask is Task saving) await saving;
                    // This assembly is already fail-closed to the disposable profile.
                    SaveManager.Instance.DeleteCurrentRun();
                    await NGame.Instance!.ReturnToMainMenu();
                    await Task.Delay(500,ct);
                    DecisionBridge.ResetForReplay();
                }
            }
        } catch(Exception e) {
            Harness.Log("replay_failure",new {error=e.ToString()});
        } finally {
            DisposeSelector(pilot);
            NGame.Instance!.GetTree().Quit(0);
        }
    }
    static void DisposeSelector(AutoSlayer pilot)
    {
        var field=AccessTools.Field(typeof(AutoSlayer),"_cardSelectorScope");
        (field.GetValue(pilot) as IDisposable)?.Dispose();field.SetValue(pilot,null);
    }
}
