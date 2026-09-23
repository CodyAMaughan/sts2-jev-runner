using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Rooms;
namespace OvernightHarness;

// Injects a captured full-run snapshot (see DecisionSnapshots/DecisionSnapshotGraph
// — round-trip verified against native combat state, enemy next-move IDs, and RNG
// stream determinism at capture time) and hands control to the SAME live decision
// loop a normal run uses, so real actions execute through the normal engine path —
// unlike SnapshotPlayback, which is deliberately read-only and shields live input.
//
// AutoSlayer.PlayRunAsync is the single loop that sequences every room of a run
// (map -> combat -> rewards -> map -> ...); it also bootstraps a BRAND NEW run
// (main menu, character select) before that loop starts, which would overwrite
// our injected state. So this doesn't call PlayRunAsync — it replicates just its
// room-sequencing while-loop (verified line-for-line against the decompiled
// source in AutoSlayer.cs) via reflection on the same private methods, seeded
// from the already-injected RunState instead of a fresh bootstrap. Everything
// inside that loop (HandleRoomAsync, the map handler, rewards/overlay/rest/event
// waits) is the game's own unmodified code — real screens, real animation.
[HarmonyPatch(typeof(AutoSlayer),"RunAsync")]
static class SnapshotResume
{
    public static bool Enabled=>!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_RESUME"));
    [HarmonyPriority(Priority.First)]
    static bool Prefix(AutoSlayer __instance,CancellationToken ct,ref Task __result){if(!Enabled)return true;__result=Run(__instance,ct);return false;}
    static async Task Run(AutoSlayer pilot,CancellationToken ct)
    {
        try
        {
            string path=Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_RESUME")!;
            var envelope=DecisionSnapshots.Read(path);
            var run=DecisionSnapshots.Inject(envelope);
            // Live interaction needs the real Godot scene built too, not just
            // the model state — see DecisionSnapshots.PresentCombatScene.
            await DecisionSnapshots.PresentCombatScene(run,envelope);
            Harness.Log("snapshot_resume_injected",new{decision_id=envelope.DecisionId,kind=envelope.Kind,combat_in_progress=envelope.CombatInProgress,floor=run.TotalFloor,room=run.CurrentRoom?.RoomType.ToString()});

            // The minimal slice of PlayRunAsync's bootstrap that isn't tied to
            // starting a fresh run: per-run RNG for AutoSlay's own random choices
            // (draft ties etc, seeded from the injected run's own seed so it's
            // still deterministic) and the card-selector scope every room handler
            // expects to exist. _roomHandlers/_mapHandler/_screenHandlers are set
            // in AutoSlayer's constructor, already valid on this instance.
            var random=new Rng((uint)StringHelper.GetDeterministicHashCode(run.Rng.StringSeed));
            AccessTools.Field(typeof(AutoSlayer),"_random").SetValue(pilot,random);
            var watchdog=new Watchdog();
            AccessTools.Field(typeof(AutoSlayer),"_watchdog").SetValue(pilot,watchdog);
            AccessTools.Property(typeof(AutoSlayer),"CurrentWatchdog").SetValue(null,watchdog);
            AccessTools.Field(typeof(AutoSlayer),"_cardSelectorScope").SetValue(pilot,CardSelectCmd.UseSelector(new AutoSlayCardSelector(random)));

            var handleRoom=AccessTools.Method(typeof(AutoSlayer),"HandleRoomAsync");
            var drainOverlays=AccessTools.Method(typeof(AutoSlayer),"DrainOverlayScreensAsync");
            var restProceed=AccessTools.Method(typeof(AutoSlayer),"ClickRestSiteProceedIfNeeded");
            var eventProceed=AccessTools.Method(typeof(AutoSlayer),"ClickEventProceedIfNeeded");
            var waitRewards=AccessTools.Method(typeof(AutoSlayer),"WaitForRewardsScreenAsync");
            var waitMainMenu=AccessTools.Method(typeof(AutoSlayer),"WaitForMainMenuAsync");
            var abandonRun=AccessTools.Method(typeof(AutoSlayer),"AbandonRunAsync");
            var mapHandler=AccessTools.Field(typeof(AutoSlayer),"_mapHandler").GetValue(pilot)!;
            var handleMap=AccessTools.Method(mapHandler.GetType(),"HandleAsync");

            // Verbatim port of AutoSlayer.PlayRunAsync's room loop (see AutoSlayer.cs)
            // starting from the already-injected room instead of a freshly-assigned one.
            while(run.TotalFloor<49)
            {
                ct.ThrowIfCancellationRequested();
                RoomType roomType=run.CurrentRoom!.RoomType;
                watchdog.Reset($"Entering {roomType} room (Act {run.CurrentActIndex+1}, Floor {run.ActFloor})");
                Harness.Log("snapshot_resume_room",new{room=roomType.ToString(),act=run.CurrentActIndex+1,floor=run.ActFloor});
                await (Task)handleRoom.Invoke(pilot,new object[]{roomType,ct})!;
                if((uint)(roomType-1)>2u)await Task.Delay(500,ct);
                else await (Task)waitRewards.Invoke(pilot,new object[]{ct})!;
                await (Task)drainOverlays.Invoke(pilot,new object[]{ct})!;
                if(roomType==RoomType.RestSite)await (Task)restProceed.Invoke(pilot,new object[]{ct})!;
                if(roomType==RoomType.Event)await (Task)eventProceed.Invoke(pilot,new object[]{ct})!;
                bool secondBoss=roomType==RoomType.Boss && run.Map.SecondBossMapPoint!=null && run.CurrentMapCoord==run.Map.BossMapPoint!.coord;
                if(roomType==RoomType.Boss && !secondBoss)
                {
                    watchdog.Reset("Waiting for act transition after boss");
                    RoomType postBossRoomType=RoomType.Boss;
                    await WaitHelper.Until(delegate {
                        var currentRoom=run.CurrentRoom;
                        if(currentRoom==null)return false;
                        postBossRoomType=currentRoom.RoomType;
                        return postBossRoomType!=RoomType.Boss;
                    },ct,TimeSpan.FromSeconds(10),"Act transition did not start after boss");
                    Harness.Log("snapshot_resume_post_boss",new{room=postBossRoomType.ToString()});
                    if(postBossRoomType==RoomType.Event && run.CurrentActIndex>=run.Acts.Count-1)
                    {
                        watchdog.Reset($"Entering {postBossRoomType} room (Act {run.CurrentActIndex+1}, Floor {run.ActFloor})");
                        await (Task)handleRoom.Invoke(pilot,new object[]{postBossRoomType,ct})!;
                        await Task.Delay(500,ct);
                        await (Task)drainOverlays.Invoke(pilot,new object[]{ct})!;
                        watchdog.Reset("Waiting for main menu after victory");
                        await (Task)waitMainMenu.Invoke(pilot,new object[]{ct})!;
                        Harness.Log("snapshot_resume_victory",new{});
                        return;
                    }
                    await WaitHelper.Until(()=>run.VisitedMapCoords.Count==0,ct,TimeSpan.FromSeconds(5),"Act transition did not complete (VisitedMapCoords not cleared)");
                }
                watchdog.Reset("Navigating map");
                await (Task)handleMap.Invoke(mapHandler,new object[]{random,ct})!;
            }
            Harness.Log("snapshot_resume_floor_cap",new{});
            await (Task)abandonRun.Invoke(pilot,new object[]{ct})!;
        }
        catch(Exception e)
        {
            Harness.Log("snapshot_resume_failed",new{error=e.ToString()});
            throw;
        }
    }
}
