using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Runs;
namespace OvernightHarness;

// The real renderer preloads VFX that the headless engine skips. Keep the
// extra allowance scoped to initial room loading, not stalled gameplay.
[HarmonyPatch(typeof(WaitHelper),nameof(WaitHelper.Until))]
static class HeadedStartupWait
{
    static void Prefix(ref TimeSpan? timeout,string? timeoutMessage)
    {
        if(Environment.GetEnvironmentVariable("DEALMAKER_HEADED")=="1" && timeoutMessage=="Room type not assigned")timeout=TimeSpan.FromSeconds(90);
    }
}
[HarmonyPatch(typeof(Watchdog),nameof(Watchdog.Check))]
static class HeadedStartupWatchdog
{
    static void Prefix(Watchdog __instance)
    {
        if(Environment.GetEnvironmentVariable("DEALMAKER_HEADED")=="1" && RunManager.Instance.DebugOnlyGetState() is {CurrentRoom:null})
            __instance.Reset("Initial rendered room load (bounded by 90-second startup timeout)");
    }
}
