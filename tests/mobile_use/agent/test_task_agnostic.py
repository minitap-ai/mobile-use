"""Fix-round hard rule: the agent stays task-agnostic.

No AndroidWorld (or MiniWoB, the held-out benchmark) app name, package, task name or benchmark
name may appear in the agent's code, prompts or benchmark configs. Generic UI words that
AndroidWorld also uses as app names (camera, clock, contacts, dialer, files, phone, settings,
tasks) are not listed: banning them would ban ordinary UI vocabulary.

Sources: upstream android_world @55ddaf5 task_metadata.json (116 task names) and the
`app_names` / `_APP_NAME` constants of android_world/task_evals.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

AW_APP_NAMES = [
    "audio recorder",
    "markor",
    "clipper",
    "simple sms messenger",
    "vlc",
    "simple calendar",
    "simple draw",
    "simple gallery",
    "joplin",
    "open tracks",
    "opentracks",
    "sports tracker",
    "osmand",
    "broccoli",
    "pro expense",
    "retro music",
    "activity tracker",
    # P2 additions
    "simple draw pro",
    "simple calendar pro",
    "broccoli app",
]
AW_PACKAGE_FRAGMENTS = [
    "gsantner",
    "flauschcode",
    "arduia",
    "simplemobiletools",
    "dimowner",
    "dennisguse",
    "net.osmand",
    "code.name.monkey",
    "videolan",
    "zgrs.clipper",
    "net.cozic",
    # P2 additions: packages of the AndroidWorld apps not covered above
    "org.tasks",
    "deskclock",
    "retromusic",
    "audiorecorder",
    "opentracks",
]
BENCHMARK_NAMES = ["androidworld", "android_world", "android world", "miniwob"]
AW_TASK_NAMES = [
    "AudioRecorderRecordAudio",
    "AudioRecorderRecordAudioWithFileName",
    "BrowserDraw",
    "BrowserMaze",
    "BrowserMultiply",
    "CameraTakePhoto",
    "CameraTakeVideo",
    "ClockStopWatchPausedVerify",
    "ClockStopWatchRunning",
    "ClockTimerEntry",
    "ContactsAddContact",
    "ContactsNewContactDraft",
    "ExpenseAddMultiple",
    "ExpenseAddMultipleFromGallery",
    "ExpenseAddMultipleFromMarkor",
    "ExpenseAddSingle",
    "ExpenseDeleteDuplicates",
    "ExpenseDeleteDuplicates2",
    "ExpenseDeleteMultiple",
    "ExpenseDeleteMultiple2",
    "ExpenseDeleteSingle",
    "FilesDeleteFile",
    "FilesMoveFile",
    "MarkorAddNoteHeader",
    "MarkorChangeNoteContent",
    "MarkorCreateFolder",
    "MarkorCreateNote",
    "MarkorCreateNoteAndSms",
    "MarkorCreateNoteFromClipboard",
    "MarkorDeleteAllNotes",
    "MarkorDeleteNewestNote",
    "MarkorDeleteNote",
    "MarkorEditNote",
    "MarkorMergeNotes",
    "MarkorMoveNote",
    "MarkorTranscribeReceipt",
    "MarkorTranscribeVideo",
    "NotesIsTodo",
    "NotesMeetingAttendeeCount",
    "NotesRecipeIngredientCount",
    "NotesTodoItemCount",
    "OpenAppTaskEval",
    "OsmAndFavorite",
    "OsmAndMarker",
    "OsmAndTrack",
    "RecipeAddMultipleRecipes",
    "RecipeAddMultipleRecipesFromImage",
    "RecipeAddMultipleRecipesFromMarkor",
    "RecipeAddMultipleRecipesFromMarkor2",
    "RecipeAddSingleRecipe",
    "RecipeDeleteDuplicateRecipes",
    "RecipeDeleteDuplicateRecipes2",
    "RecipeDeleteDuplicateRecipes3",
    "RecipeDeleteMultipleRecipes",
    "RecipeDeleteMultipleRecipesWithConstraint",
    "RecipeDeleteMultipleRecipesWithNoise",
    "RecipeDeleteSingleRecipe",
    "RecipeDeleteSingleWithRecipeWithNoise",
    "RetroCreatePlaylist",
    "RetroPlayingQueue",
    "RetroPlaylistDuration",
    "RetroSavePlaylist",
    "SaveCopyOfReceiptTaskEval",
    "SimpleCalendarAddOneEvent",
    "SimpleCalendarAddOneEventInTwoWeeks",
    "SimpleCalendarAddOneEventRelativeDay",
    "SimpleCalendarAddOneEventTomorrow",
    "SimpleCalendarAddRepeatingEvent",
    "SimpleCalendarAnyEventsOnDate",
    "SimpleCalendarDeleteEvents",
    "SimpleCalendarDeleteEventsOnRelativeDay",
    "SimpleCalendarDeleteOneEvent",
    "SimpleCalendarEventOnDateAtTime",
    "SimpleCalendarEventsInNextWeek",
    "SimpleCalendarEventsInTimeRange",
    "SimpleCalendarEventsOnDate",
    "SimpleCalendarFirstEventAfterStartTime",
    "SimpleCalendarLocationOfEvent",
    "SimpleCalendarNextEvent",
    "SimpleCalendarNextMeetingWithPerson",
    "SimpleDrawProCreateDrawing",
    "SimpleSmsReply",
    "SimpleSmsReplyMostRecent",
    "SimpleSmsResend",
    "SimpleSmsSend",
    "SimpleSmsSendClipboardContent",
    "SimpleSmsSendReceivedAddress",
    "SportsTrackerActivitiesCountForWeek",
    "SportsTrackerActivitiesOnDate",
    "SportsTrackerActivityDuration",
    "SportsTrackerLongestDistanceActivity",
    "SportsTrackerTotalDistanceForCategoryOverInterval",
    "SportsTrackerTotalDurationForCategoryThisWeek",
    "SystemBluetoothTurnOff",
    "SystemBluetoothTurnOffVerify",
    "SystemBluetoothTurnOn",
    "SystemBluetoothTurnOnVerify",
    "SystemBrightnessMax",
    "SystemBrightnessMaxVerify",
    "SystemBrightnessMin",
    "SystemBrightnessMinVerify",
    "SystemCopyToClipboard",
    "SystemWifiTurnOff",
    "SystemWifiTurnOffVerify",
    "SystemWifiTurnOn",
    "SystemWifiTurnOnVerify",
    "TasksCompletedTasksForDate",
    "TasksDueNextWeek",
    "TasksDueOnDate",
    "TasksHighPriorityTasks",
    "TasksHighPriorityTasksDueOnDate",
    "TasksIncompleteTasksOnDate",
    "TurnOffWifiAndTurnOnBluetooth",
    "TurnOnWifiAndOpenApp",
    "VlcCreatePlaylist",
    "VlcCreateTwoPlaylists",
]

SCANNED = [
    *sorted((ROOT / "minitap" / "mobile_use").rglob("*.md")),
    *sorted((ROOT / "minitap" / "mobile_use").rglob("*.py")),
    *sorted((ROOT / "minitap" / "mobile_use").rglob("*.jinja*")),
    *sorted((ROOT / "benchmarks" / "configs").rglob("*.jsonc")),
    ROOT / "llm-config.defaults.jsonc",
]
# Measurement-only code, never part of a prompt or of an agent decision: the benchmark harness
# glue (run_task, recorder, configs loader) and the paper-era W&B logger (inert unless a task name
# carries a W&B run id). Everything the LLMs read (prompts, tool descriptions, agent code) is
# scanned.
EXCLUDED = (
    ROOT / "minitap" / "mobile_use" / "benchmark",
    ROOT / "minitap" / "mobile_use" / "observability" / "wandb_provider.py",
)
SCANNED = [
    p
    for p in SCANNED
    if not p.name.startswith("test_") and not any(p == e or e in p.parents for e in EXCLUDED)
]
BRANCH_TOKEN = "paper/androidworld-rework"  # our own branch name in code comments


def _hits(text: str) -> list[str]:
    text = text.replace(BRANCH_TOKEN, "")
    low = text.lower()
    hits = [w for w in AW_APP_NAMES + AW_PACKAGE_FRAGMENTS + BENCHMARK_NAMES if w in low]
    hits += [t for t in AW_TASK_NAMES if re.search(rf"\b{re.escape(t)}\b", text)]
    return hits


def test_lists_are_not_empty():
    assert len(AW_TASK_NAMES) == 116 and len(AW_APP_NAMES) >= 15


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_androidworld_names_in_agent_prompts_code_or_configs(path):
    hits = _hits(path.read_text(encoding="utf-8", errors="replace"))
    assert hits == [], f"{path.relative_to(ROOT)} mentions {hits}"


def test_detector_catches_a_planted_name():
    assert _hits("Open Markor and run ExpenseDeleteDuplicates") == [
        "markor",
        "ExpenseDeleteDuplicates",
    ]
