"""
trivia_system.py — RotMG Trivia system for The Atheneum Discord bot.

Commands:
  !trivia start [easy|medium|hard|expert|all]  — Start a round
  !trivia quick                                 — One random question
  !trivia stop                                  — Stop active round
  !trivia scores                                — All-time leaderboard
  !trivia add <question> | <answer> | [alt] | [hint]  — Add custom question
  !trivia list [category]                       — Browse question categories
  !trivia stats <player>                        — Player's trivia stats
"""

import json
import os
import asyncio
import random
from typing import Optional

QUESTIONS_FILE = "trivia_questions.json"
SCORES_FILE    = "trivia_scores.json"

# ── Difficulty settings ───────────────────────────────────────────────────────
DIFFICULTY_CONFIG = {
    "easy":   {"timeout": 25, "points": 1,  "hint_at": 0.5},
    "medium": {"timeout": 20, "points": 2,  "hint_at": 0.5},
    "hard":   {"timeout": 15, "points": 3,  "hint_at": 0.6},
    "expert": {"timeout": 12, "points": 5,  "hint_at": 0.4},
}

DIFFICULTY_EMOJI = {
    "easy":   "🟢",
    "medium": "🟡",
    "hard":   "🔴",
    "expert": "💀",
}

CATEGORY_EMOJI = {
    "General":  "⚔️",
    "Events":   "🌍",
    "Dungeons": "🏰",
    "Lore":     "📜",
}

# ── Score / data helpers ──────────────────────────────────────────────────────

def load_scores() -> dict:
    if not os.path.exists(SCORES_FILE):
        return {}
    try:
        with open(SCORES_FILE, encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception:
        return {}


def save_scores(scores: dict):
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)


def add_score(player: str, points: int, difficulty: str):
    scores = load_scores()
    if player not in scores:
        scores[player] = {
            "total_points": 0,
            "correct":      0,
            "by_difficulty": {k: 0 for k in DIFFICULTY_CONFIG}
        }
    scores[player]["total_points"] += points
    scores[player]["correct"]      += 1
    scores[player]["by_difficulty"][difficulty] = \
        scores[player]["by_difficulty"].get(difficulty, 0) + 1
    save_scores(scores)


def load_questions(difficulty: str = "all") -> list:
    if not os.path.exists(QUESTIONS_FILE):
        return []
    try:
        with open(QUESTIONS_FILE, encoding="utf-8") as f:
            questions = json.load(f)
    except Exception:
        return []

    if difficulty == "all":
        return questions
    return [q for q in questions if q.get("difficulty", "medium") == difficulty]


def save_custom_question(q: dict):
    questions = load_questions("all")
    questions.append(q)
    with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)


# ── Leaderboard scroll builder ────────────────────────────────────────────────

def build_scores_scroll(top_n: int = 10) -> str:
    scores = load_scores()
    if not scores:
        return "No trivia scores yet!"

    board   = sorted(scores.items(), key=lambda x: x[1]["total_points"], reverse=True)
    medals  = ["(1)", "(2)", "(3)"]
    W       = 46

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    lines = [top_(), ctr_("~ Trivia Leaderboard ~"), mid_()]
    lines.append(row_(f"{'Player':<18} {'Pts':>6}  {'Correct':>8}  {'Best':>8}"))
    lines.append(mid_())

    for i, (name, data) in enumerate(board[:top_n]):
        medal   = medals[i] if i < 3 else f"({i+1})"
        pts     = data.get("total_points", 0)
        correct = data.get("correct", 0)
        # Find their best difficulty
        by_diff = data.get("by_difficulty", {})
        best    = max(by_diff, key=by_diff.get) if by_diff else "—"
        best_emoji = DIFFICULTY_EMOJI.get(best, "")
        lines.append(row_(
            f"{medal} {name[:16]:<16} {pts:>6}  {correct:>8}  {best_emoji}{best:>6}"
        ))

    lines.append(bot_())
    return "```\n" + "\n".join(lines) + "\n```"


def build_player_stats_scroll(player: str) -> str:
    scores = load_scores()
    data   = scores.get(player)
    if not data:
        return f"No trivia stats found for **{player}**."

    W = 36
    def line(t=""): return f"    |{t:^{W}}|."
    def div():      return f"    |{'~' * W}|."
    def sline(l, v):
        content = f" {l}: {v}"
        return [f"    |{content:<{W}}|."] if len(content) <= W else \
               [f"    | {l}:{' '*(W-len(l)-2)}|.", f"    |   {str(v)[:W-4]:<{W-4}}|."]

    scroll = [
        f"   {'_' * W}",
        f" / \\{' ' * W}\\.",
        f"|   |{' ' * W}|.",
        line("~ TRIVIA STATS ~"),
        f" \\_ |{player[:W]:^{W}}|.",
        line(),
        div(),
        line(),
    ]
    scroll += sline("Total Points",  data.get("total_points", 0))
    scroll += sline("Questions Won", data.get("correct", 0))
    scroll.append(line())
    scroll.append(div())
    scroll.append(line())
    scroll.append(f"    | {'By Difficulty:':<{W-1}}|.")
    for diff, emoji in DIFFICULTY_EMOJI.items():
        count = data.get("by_difficulty", {}).get(diff, 0)
        scroll += sline(f"  {emoji} {diff.title()}", count)
    scroll.append(line())
    scroll.append(f"    |   {'_' * W}|___")
    scroll.append(f"    |  /{' ' * W}/.")
    scroll.append(f"    \\_/{'_' * W}/.")

    return "```\n" + "\n".join(scroll) + "\n```"


# ── Core question logic ───────────────────────────────────────────────────────

async def ask_question(
    bot,
    channel,
    question:      dict,
    question_num:  int = 1,
    total:         int = 1,
) -> tuple:
    """
    Ask one question, wait for correct answer.
    Returns (winner_display_name | None, points_awarded).
    """
    diff    = question.get("difficulty", "medium")
    cfg     = DIFFICULTY_CONFIG.get(diff, DIFFICULTY_CONFIG["medium"])
    timeout = cfg["timeout"]
    points  = cfg["points"]
    hint_at = cfg["hint_at"]
    hint    = question.get("hint", "")
    answers = [a.lower().strip() for a in question["a"]]
    cat     = question.get("category", "General")
    emoji   = DIFFICULTY_EMOJI.get(diff, "")
    cat_e   = CATEGORY_EMOJI.get(cat, "❓")

    await channel.send(
        f"{emoji} **Q{question_num}/{total}** {cat_e} `{cat}` — `{diff.upper()}`\n"
        f"**{question['q']}**\n"
        f"⏱️ {timeout} seconds — worth **{points}** point{'s' if points != 1 else ''}!"
    )

    def check(msg):
        return (
            msg.channel == channel and
            not msg.author.bot and
            msg.content.lower().strip() in answers
        )

    start      = asyncio.get_event_loop().time()
    hint_sent  = False

    while True:
        elapsed   = asyncio.get_event_loop().time() - start
        remaining = timeout - elapsed

        if remaining <= 0:
            break

        # Send hint at the configured point
        if not hint_sent and hint and elapsed >= timeout * hint_at:
            await channel.send(f"💡 **Hint:** {hint}")
            hint_sent = True

        try:
            msg = await bot.wait_for(
                "message", check=check,
                timeout=min(1.5, remaining)
            )
            winner = msg.author.display_name
            await channel.send(
                f"✅ **{winner}** got it! "
                f"The answer was **{question['a'][0]}** "
                f"(+{points} pt{'s' if points != 1 else ''})"
            )
            add_score(winner, points, diff)
            return winner, points
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            return None, 0

    await channel.send(
        f"⏰ Time's up! The answer was **{question['a'][0]}**"
    )
    return None, 0


async def run_trivia_round(
    bot,
    channel,
    difficulty:    str = "all",
    num_questions: int = 5,
    stop_flag:     list = None,   # mutable list used as flag: [False]
):
    """
    Run a full trivia round.
    stop_flag is a single-element list so the command handler can signal stop.
    """
    questions = load_questions(difficulty)
    if not questions:
        await channel.send(f"No questions found for difficulty: **{difficulty}**")
        return

    random.shuffle(questions)
    selected     = questions[:num_questions]
    round_scores = {}   # display_name -> points

    diff_label = difficulty.title() if difficulty != "all" else "Mixed"
    await channel.send(
        f"🎮 **RotMG Trivia — {diff_label} Round!**\n"
        f"{num_questions} questions · Difficulty varies · Type your answer in chat!\n"
        f"Starting in 3 seconds..."
    )
    await asyncio.sleep(3)

    for i, q in enumerate(selected, 1):
        if stop_flag and stop_flag[0]:
            await channel.send("⛔ Trivia round stopped.")
            break

        winner, pts = await ask_question(bot, channel, q, i, num_questions)
        if winner:
            round_scores[winner] = round_scores.get(winner, 0) + pts

        # Short pause between questions
        await asyncio.sleep(3)

    # ── Round summary ─────────────────────────────────────────────────────────
    if not round_scores:
        await channel.send("😔 Nobody answered any questions this round!")
        return

    winner_name = max(round_scores, key=round_scores.get)
    medals      = ["(1)", "(2)", "(3)"]
    W           = 38

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    lines = [top_(), ctr_("~ Round Results ~"), mid_()]
    sorted_scores = sorted(round_scores.items(), key=lambda x: x[1], reverse=True)
    for idx, (name, pts) in enumerate(sorted_scores):
        medal = medals[idx] if idx < 3 else f"({idx+1})"
        lines.append(row_(f"{medal} {name[:18]:<18} {pts:>8} pts"))
    lines.append(mid_())
    lines.append(ctr_(f"🏆 Round Winner: {winner_name}!"))
    lines.append(bot_())
    await channel.send("```\n" + "\n".join(lines) + "\n```")
