import os
import random
import datetime
from typing import Dict, List, Tuple

import discord
from discord.ext import commands

# ================== CONFIG BOT ==================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    # Sur Railway, ça s'affichera dans les logs si la variable n'est pas définie
    raise SystemExit("DISCORD_TOKEN non défini dans les variables d'environnement.")

PREFIX = "!"
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ================== OUTILS TEMPS & ALLURES ==================

def parse_time_to_seconds(time_str: str) -> int:
    """mm:ss ou hh:mm:ss -> secondes"""
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError("Format invalide. Utilise mm:ss ou hh:mm:ss")
    h = int(hours)
    m = int(minutes)
    s = int(seconds)
    return h * 3600 + m * 60 + s

def seconds_to_pace_str(seconds_per_km: float) -> str:
    minutes = int(seconds_per_km // 60)
    seconds = int(round(seconds_per_km % 60))
    return f"{minutes:d}:{seconds:02d} /km"

def format_time(seconds: float) -> str:
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    else:
        return f"{m:d}:{s:02d}"

def estimate_vma_from_5k(time_seconds: int) -> float:
    """VMA approximative à partir du chrono 5 km (en secondes)."""
    distance_km = 5.0
    hours = time_seconds / 3600
    speed_kmh = distance_km / hours
    vma = speed_kmh / 0.92
    return vma

def estimate_vo2max_from_5k(time_seconds: int) -> float:
    """Estim VO2max à partir du 5 km via Daniels."""
    distance_m = 5000
    speed_m_per_s = distance_m / time_seconds
    speed_m_per_min = speed_m_per_s * 60
    vo2 = -4.60 + 0.182258 * speed_m_per_min + 0.000104 * (speed_m_per_min ** 2)
    return vo2

def riegel_predict_time(t1_sec: int, d1_km: float, d2_km: float, exponent: float = 1.06) -> float:
    """Prédiction de temps (Riegel)"""
    return t1_sec * (d2_km / d1_km) ** exponent

def pace_from_speed_kmh(speed_kmh: float) -> float:
    """km/h -> secondes par km"""
    speed_m_per_s = (speed_kmh * 1000) / 3600
    return 1000 / speed_m_per_s

# ================== PROFILS & JOURNAL UTILISATEURS ==================

class RunnerProfile:
    def __init__(self, vma: float = None, five_k_time: int = None, max_hr: int = None):
        self.vma = vma
        self.five_k_time = five_k_time
        self.max_hr = max_hr

# user_id -> RunnerProfile
profiles: Dict[int, RunnerProfile] = {}

# journal des séances simples : user_id -> List[(date_iso, description)]
training_log: Dict[int, List[Tuple[str, str]]] = {}

# ================== COMMANDES ==================

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="!help pour voir les commandes"))

# 1) HELP GLOBAL
@bot.command(name="help")
async def help_command(ctx):
    msg = (
        "🏃‍♂️ **Commandes RUNNING dispo :**\n\n"
        "__Profil & bases__\n"
        "`!set5k mm:ss` → Enregistre ton chrono 5 km\n"
        "`!setvma valeur` → Fixe ta VMA (km/h)\n"
        "`!setmaxhr bpm` → Fixe ta FC max\n"
        "`!profil` → Affiche ton profil coureur\n\n"
        "__Calculs & allures__\n"
        "`!vo2` → Estime ta VO2max (si 5 km enregistré)\n"
        "`!vma` → Estime/affiche ta VMA\n"
        "`!paces` → Tableau de tes allures d'entraînement\n"
        "`!predict distance_km` → Prédiction de temps (5→10, semi, etc.)\n"
        "`!zoneshr` → Zones cardio (si FC max définie)\n"
        "`!zonespace` → Allures faciles / seuil / 10k / 5k\n\n"
        "__Plans & séances__\n"
        "`!plan5k niveau` → Plan 5 km 8 semaines (debutant/inter/avance)\n"
        "`!plan10k niveau` → Plan 10 km 10 semaines\n"
        "`!plan21k niveau` → Plan semi-marathon 12 semaines\n"
        "`!session type` → Propose une séance (endurance/vma/seuil/fartlek/cotes)\n"
        "`!taper distance_km` → Conseils de semaine d'affûtage avant course\n\n"
        "__Suivi & mental__\n"
        "`!log distance_km temps` → Ajoute une séance à ton journal\n"
        "`!history [nb]` → Affiche tes dernières séances\n"
        "`!raceday distance_km` → Routine jour de course (sommeil, repas, échauffement)\n"
    )
    await ctx.send(msg)

# 2) SET 5K
@bot.command(name="set5k")
async def set5k_command(ctx, temps_5k: str):
    try:
        t = parse_time_to_seconds(temps_5k)
    except ValueError as e:
        await ctx.send(f"❌ {e}")
        return
    prof = profiles.get(ctx.author.id, RunnerProfile())
    prof.five_k_time = t
    if prof.vma is None:
        prof.vma = estimate_vma_from_5k(t)
    profiles[ctx.author.id] = prof
    await ctx.send(f"✅ 5 km enregistré : **{temps_5k}**\nVMA estimée : **{prof.vma:.1f} km/h**")

# 3) SET VMA
@bot.command(name="setvma")
async def setvma_command(ctx, vma: float):
    prof = profiles.get(ctx.author.id, RunnerProfile())
    prof.vma = vma
    profiles[ctx.author.id] = prof
    await ctx.send(f"✅ VMA enregistrée : **{vma:.1f} km/h**")

# 4) SET MAX HR
@bot.command(name="setmaxhr")
async def setmaxhr_command(ctx, max_hr: int):
    prof = profiles.get(ctx.author.id, RunnerProfile())
    prof.max_hr = max_hr
    profiles[ctx.author.id] = prof
    await ctx.send(f"✅ Fréquence cardiaque max enregistrée : **{max_hr} bpm**")

# 5) PROFIL
@bot.command(name="profil")
async def profil_command(ctx):
    prof = profiles.get(ctx.author.id)
    if not prof:
        await ctx.send("ℹ️ Aucun profil trouvé. Commence par `!set5k mm:ss` ou `!setvma valeur`.")
        return
    desc = []
    if prof.five_k_time:
        desc.append(f"• 5 km : **{format_time(prof.five_k_time)}**")
    if prof.vma:
        desc.append(f"• VMA : **{prof.vma:.1f} km/h**")
    if prof.max_hr:
        desc.append(f"• FC max : **{prof.max_hr} bpm**")
    if not desc:
        await ctx.send("ℹ️ Profil vide. Utilise `!set5k`, `!setvma`, `!setmaxhr`.")
        return
    await ctx.send("👤 **Ton profil coureur :**\n" + "\n".join(desc))

# 6) VO2
@bot.command(name="vo2")
async def vo2_command(ctx):
    prof = profiles.get(ctx.author.id)
    if not prof or not prof.five_k_time:
        await ctx.send("❌ Tu dois d'abord enregistrer un 5 km avec `!set5k mm:ss`.")
        return
    vo2 = estimate_vo2max_from_5k(prof.five_k_time)
    await ctx.send(f"🧠 VO2max estimée : **{vo2:.1f} ml/kg/min** (approx)")

# 7) VMA
@bot.command(name="vma")
async def vma_command(ctx):
    prof = profiles.get(ctx.author.id)
    if prof and prof.vma:
        await ctx.send(f"🏃‍♂️ Ta VMA enregistrée/estimée est : **{prof.vma:.1f} km/h**")
        return
    if prof and prof.five_k_time:
        vma = estimate_vma_from_5k(prof.five_k_time)
        profiles[ctx.author.id].vma = vma
        await ctx.send(f"🏃‍♂️ VMA estimée à partir du 5 km : **{vma:.1f} km/h**")
        return
    await ctx.send("❌ Tu dois d'abord mettre un 5 km (`!set5k`) ou une VMA (`!setvma`).")

# 8) PACES
@bot.command(name="paces")
async def paces_command(ctx):
    prof = profiles.get(ctx.author.id)
    if not prof or not prof.vma:
        await ctx.send("❌ Il me faut ta VMA (`!setvma` ou `!set5k`).")
        return
    vma = prof.vma
    zones = {
        "Endurance fondamentale (~60–70% VMA)": 0.65,
        "Endurance active (~70–75% VMA)": 0.72,
        "Allure marathon (~78–82% VMA)": 0.80,
        "Allure seuil (~88–92% VMA)": 0.90,
        "Allure 10 km (~95% VMA)": 0.95,
        "Allure 5 km (~100–105% VMA)": 1.02,
        "Fractionné court (105–110% VMA)": 1.08,
    }
    lines = []
    for label, coef in zones.items():
        speed = vma * coef
        pace_sec = pace_from_speed_kmh(speed)
        lines.append(f"- {label} : **{seconds_to_pace_str(pace_sec)}** (~{speed:.1f} km/h)")
    await ctx.send("📏 **Tes allures d'entraînement (approx.) :**\n" + "\n".join(lines))

# 9) PREDICT
@bot.command(name="predict")
async def predict_command(ctx, distance_km: float):
    prof = profiles.get(ctx.author.id)
    if not prof or not prof.five_k_time:
        await ctx.send("❌ Tu dois d'abord enregistrer un 5 km avec `!set5k mm:ss`.")
        return
    base = prof.five_k_time
    if distance_km <= 0:
        await ctx.send("❌ Distance invalide.")
        return
    predicted = riegel_predict_time(base, 5.0, distance_km)
    await ctx.send(
        f"⏱️ Temps estimé sur **{distance_km:.1f} km** : **{format_time(predicted)}**\n"
        "(Basé sur ton 5 km et le modèle de Riegel, approximatif)"
    )

# 10) ZONES HR
@bot.command(name="zoneshr")
async def zoneshr_command(ctx):
    prof = profiles.get(ctx.author.id)
    if not prof or not prof.max_hr:
        await ctx.send("❌ Il me faut ta FC max (bpm) avec `!setmaxhr`.")
        return
    m = prof.max_hr
    zones = [
        ("Zone 1 (récup)", 0.50, 0.60),
        ("Zone 2 (endurance)", 0.60, 0.70),
        ("Zone 3 (tempo / seuil bas)", 0.70, 0.80),
        ("Zone 4 (seuil / VO2)", 0.80, 0.90),
        ("Zone 5 (anaérobie)", 0.90, 1.00),
    ]
    lines = []
    for name, low, high in zones:
        lines.append(f"- {name} : **{int(m*low)}–{int(m*high)} bpm**")
    await ctx.send("❤️ **Tes zones cardio (approx.) :**\n" + "\n".join(lines))

# 11) ZONES PACES SIMPLIFIEES
@bot.command(name="zonespace")
async def zonespace_command(ctx):
    prof = profiles.get(ctx.author.id)
    if not prof or not prof.vma:
        await ctx.send("❌ Il me faut ta VMA (`!setvma` ou `!set5k`).")
        return
    vma = prof.vma
    labels = {
        "Footing très facile": 0.60,
        "Footing normal": 0.70,
        "Allure marathon": 0.80,
        "Allure seuil": 0.90,
        "Allure 10 km": 0.95,
        "Allure 5 km": 1.02,
    }
    lines = []
    for name, coef in labels.items():
        spd = vma * coef
        pace_sec = pace_from_speed_kmh(spd)
        lines.append(f"- {name} : **{seconds_to_pace_str(pace_sec)}** (~{spd:.1f} km/h)")
    await ctx.send("🏷️ **Résumé de tes allures clés :**\n" + "\n".join(lines))

# 12) PLANS 5K / 10K / 21K (très simplifiés)

def build_plan(distance: str, weeks: int, level: str) -> str:
    level = level.lower()
    if level not in ("debutant", "inter", "avance"):
        level = "inter"
    lines = [f"📅 Plan {distance} — {weeks} semaines — Niveau **{level}**"]
    for w in range(1, weeks+1):
        if level == "debutant":
            lines.append(f"Semaine {w} : 3 séances (2 footings, 1 séance structurée légère)")
        elif level == "avance":
            lines.append(f"Semaine {w} : 5–6 séances (vma, seuil, allure {distance}, long)")
        else:
            lines.append(f"Semaine {w} : 4 séances (endurance, vma, seuil, sortie longue)")
    lines.append("\nDétail complet à personnaliser selon ta fatigue/sensations.")
    return "\n".join(lines)

@bot.command(name="plan5k")
async def plan5k_command(ctx, niveau: str = "inter"):
    await ctx.send(build_plan("5 km", 8, niveau))

@bot.command(name="plan10k")
async def plan10k_command(ctx, niveau: str = "inter"):
    await ctx.send(build_plan("10 km", 10, niveau))

@bot.command(name="plan21k")
async def plan21k_command(ctx, niveau: str = "inter"):
    await ctx.send(build_plan("semi-marathon", 12, niveau))

# 13) SESSION TYPE
@bot.command(name="session")
async def session_command(ctx, type: str = "random"):
    type = type.lower()
    options = ["endurance", "seuil", "vma", "fartlek", "cotes"]
    if type not in options and type != "random":
        await ctx.send("Types possibles : `endurance`, `seuil`, `vma`, `fartlek`, `cotes`, ou `random`.")
        return
    if type == "random":
        type = random.choice(options)

    if type == "endurance":
        text = (
            "🟢 **Séance endurance fondamentale**\n"
            "- 45–60′ footing très facile (Z1–Z2)\n"
            "- Tu dois pouvoir parler sans être essoufflé\n"
            "- Objectif : construire le fond, récupérer"
        )
    elif type == "seuil":
        text = (
            "🟠 **Séance seuil**\n"
            "- 20′ footing\n"
            "- Puis 3 × 10′ à allure seuil (Z3) avec 3′ trot entre\n"
            "- 10′ retour au calme\n"
            "- Objectif : améliorer ta résistance à une allure soutenue"
        )
    elif type == "vma":
        text = (
            "🔺 **Séance VMA**\n"
            "- 20′ footing\n"
            "- 10 × 400m à ~100–105% VMA, récup 1′ trot\n"
            "- 10′ retour au calme\n"
            "- Objectif : monter ta vitesse max aérobie"
        )
    elif type == "fartlek":
        text = (
            "🌪️ **Séance fartlek libre**\n"
            "- 20′ footing\n"
            "- 8 à 12 × (1′ rapide / 1′ lent)\n"
            "- Allure rapide proche 5 km, allure lente footing\n"
            "- 10′ retour au calme\n"
            "- Objectif : varier les allures, travailler la relance"
        )
    else:  # cotes
        text = (
            "⛰️ **Séance côte**\n"
            "- 20′ footing\n"
            "- 10 × 20–30″ en côte, récup en marchant en descente\n"
            "- 10′ footing\n"
            "- Objectif : puissance, gainage, foulée"
        )
    await ctx.send(text)

# 14) TAPER (AFFÛTAGE)
@bot.command(name="taper")
async def taper_command(ctx, distance_km: float):
    if distance_km <= 0:
        await ctx.send("❌ Distance invalide.")
        return
    if distance_km <= 5:
        msg = (
            "🎯 **Affûtage 5 km (4–5 jours avant)**\n"
            "- J-4 : séance allure course (3 × 5′ / récup 3′)\n"
            "- J-3 : footing 30–40′ facile\n"
            "- J-2 : repos ou 20′ très facile + 3 lignes droites\n"
            "- J-1 : repos, hydratation, repas léger\n"
        )
    elif distance_km <= 10:
        msg = (
            "🎯 **Affûtage 10 km (7 jours)**\n"
            "- Volume réduit de ~30–40%\n"
            "- 1 séance allure 10k (ex : 3 × 8′)\n"
            "- 1 séance légère de rappel VMA (ex : 6 × 200m)\n"
            "- Le reste en footing facile\n"
        )
    elif distance_km <= 25:
        msg = (
            "🎯 **Affûtage semi-marathon (10–14 jours)**\n"
            "- Réduire progressivement le volume (−30 à −40%)\n"
            "- Garder un peu d'allure spécifique (ex : 3 × 3 km)\n"
            "- Dernière sortie longue à J-10 environ\n"
            "- Semaine de course : mostly footings faciles\n"
        )
    else:
        msg = (
            "🎯 **Affûtage marathon / longue distance**\n"
            "- Taper sur 2–3 semaines\n"
            "- Réduction progressive du volume (jusqu'à −50%)\n"
            "- Garder quelques blocs allure marathon\n"
            "- Beaucoup de sommeil, gestion du stress et de la nutrition\n"
        )
    await ctx.send(msg)

# 15) LOG & HISTORY

@bot.command(name="log")
async def log_command(ctx, distance_km: float, temps: str):
    try:
        t = parse_time_to_seconds(temps)
    except ValueError as e:
        await ctx.send(f"❌ {e}")
        return
    date_str = datetime.date.today().isoformat()
    desc = f"{date_str} — {distance_km:.1f} km en {format_time(t)}"
    training_log.setdefault(ctx.author.id, []).append((date_str, desc))
    await ctx.send(f"📝 Séance enregistrée : {desc}")

@bot.command(name="history")
async def history_command(ctx, nb: int = 5):
    logs = training_log.get(ctx.author.id, [])
    if not logs:
        await ctx.send("📂 Aucun entraînement enregistré. Utilise `!log distance temps`.")
        return
    nb = max(1, min(nb, 20))
    recent = logs[-nb:]
    lines = [d for _, d in recent]
    await ctx.send("📚 **Tes dernières séances :**\n" + "\n".join(lines))

# 16) RACEDAY CONSEILS
@bot.command(name="raceday")
async def raceday_command(ctx, distance_km: float):
    base = (
        "🧠 **Routine jour de course :**\n"
        "- Dors bien les 2–3 nuits AVANT la course\n"
        "- Petit déjeuner facile à digérer 2–3h avant\n"
        "- Hydrate-toi régulièrement mais sans abuser\n"
        "- Arrive tôt sur place pour éviter le stress\n"
        "- Échauffement progressif + quelques accélérations\n"
        "- Ne pars pas trop vite, surtout au 1er km\n"
    )
    if distance_km <= 5:
        spec = (
            "\nSpécifique 5 km :\n"
            "- Échauffement plus long (15–20′)\n"
            "- Allure vite proche du max → prépare-toi mentalement à l'inconfort\n"
        )
    elif distance_km <= 10:
        spec = (
            "\nSpécifique 10 km :\n"
            "- Vise une allure régulière du km 1 au km 8\n"
            "- Si tu es bien, accélère légèrement sur les 2 derniers km\n"
        )
    elif distance_km <= 25:
        spec = (
            "\nSpécifique semi :\n"
            "- Garde une allure contrôlée jusqu'au km 15\n"
            "- Attention à la nutrition : un gel tous les 30–40′ peut aider\n"
        )
    else:
        spec = (
            "\nSpécifique longue distance :\n"
            "- Gère ton allure dès le départ, le marathon commence après le 30e km\n"
            "- Plan nutrition précis (eau + glucides régulièrement)\n"
        )
    await ctx.send(base + spec)

# ================== LANCEMENT ==================

if __name__ == "__main__":
    bot.run(TOKEN)
