import discord
from discord.ext import commands
import random

# ---------- CONFIG BOT ----------

import os
TOKEN = os.getenv("DISCORD_TOKEN") 

PREFIX = "!"  # commandes : !vo2, !edj, etc.

intents = discord.Intents.default()
intents.message_content = True  # nécessaire pour lire le contenu des messages

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


# ---------- FONCTIONS SPORTIVES VO2 / VMA ----------

def parse_time_to_seconds(time_str: str) -> int:
    """
    Convertit un temps au format mm:ss ou hh:mm:ss en secondes.
    Ex : '19:35' -> 1175 s
    """
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError("Format de temps invalide. Utilise mm:ss ou hh:mm:ss")

    h = int(hours)
    m = int(minutes)
    s = int(seconds)
    return h * 3600 + m * 60 + s


def seconds_to_pace_min_km(seconds_per_km: float) -> str:
    """
    Convertit un temps par km (en secondes) en format mm:ss /km.
    Ex : 240 s/km -> '4:00 /km'
    """
    minutes = int(seconds_per_km // 60)
    seconds = int(round(seconds_per_km % 60))
    return f"{minutes:d}:{seconds:02d} /km"


def format_time(seconds: float) -> str:
    """
    Convertit un temps total en format h:mm:ss ou m:ss.
    """
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    else:
        return f"{m:d}:{s:02d}"


def estimate_vo2max_from_5k(time_seconds: int) -> float:
    """
    Estimation VO2max à partir du temps sur 5 km.
    Distance = 5000 m.
    Approximation type Daniels (simplifiée).
    """
    distance_m = 5000
    speed_m_per_s = distance_m / time_seconds
    speed_m_per_min = speed_m_per_s * 60

    vo2 = -4.60 + 0.182258 * speed_m_per_min + 0.000104 * (speed_m_per_min ** 2)
    return vo2  # ml/kg/min


def estimate_vma_from_5k(time_seconds: int) -> float:
    """
    Approximation de la VMA (km/h) à partir du temps 5km.
    Hypothèse : 5km couru à ~92% de la VMA.
    """
    distance_km = 5.0
    hours = time_seconds / 3600
    speed_kmh = distance_km / hours

    vma = speed_kmh / 0.92
    return vma


def threshold_pace_from_vma(vma_kmh: float) -> float:
    """
    Approximation de l'allure seuil (secondes/km) à partir de la VMA.
    Seuil ~ 89% VMA.
    """
    seuil_speed_kmh = vma_kmh * 0.89
    speed_m_per_s = (seuil_speed_kmh * 1000) / 3600
    seconds_per_km = 1000 / speed_m_per_s
    return seconds_per_km


def riegel_predict_time(t1_sec: int, d1_km: float, d2_km: float, exponent: float = 1.06) -> float:
    """
    Prédiction de temps sur une autre distance avec la formule de Riegel.
    T2 = T1 * (D2/D1)^exponent
    """
    return t1_sec * (d2_km / d1_km) ** exponent


# ---------- GENERATEUR D'ENTRAINEMENT DU JOUR (EDJ) ----------

def generate_edj(duration_min: int = 45, focus: str = "mix") -> dict:
    """
    Génère un entraînement du jour simple en fonction de la durée et du focus :
    - focus = "run", "boxe" ou "mix"
    Retourne un dict avec titre, warm, main, cool, focus.
    """
    duration_min = max(20, min(duration_min, 120))
    focus = focus.lower()
    if focus not in ("run", "boxe", "mix"):
        focus = "mix"

    if focus == "run":
        types = ["endurance", "seuil", "vma_courte", "vma_longue", "fartlek"]
        t = random.choice(types)

        if t == "endurance":
            main = (
                f"🟢 Endurance fondamentale ~{duration_min - 10}′ en Z1–Z2\n"
                "- Respiration facile, tu dois pouvoir parler\n"
                "- Objectif : accumuler du volume sans fatigue"
            )
            warm = "10′ footing très tranquille + 3 lignes droites"
            cool = "5–10′ retour au calme + étirements légers"

        elif t == "seuil":
            main = (
                "🟠 Seuil : 3 × 8′ à allure seuil (Z3–Z4)\n"
                "- Récup : 3′ trot entre les blocs\n"
                "- Allure : environ allure 10 km"
            )
            warm = "15′ footing + 4 lignes droites"
            cool = "10′ footing très cool"

        elif t == "vma_courte":
            main = (
                "🔺 VMA courte : 10 × 400m à ~100–105% VMA\n"
                "- Récup : 1′ trot entre chaque\n"
                "- Allure : légèrement plus rapide que ton allure 5 km"
            )
            warm = "15′ footing + éducatifs (montées de genoux, talons-fesses)"
            cool = "10′ footing + étirements"

        elif t == "vma_longue":
            main = (
                "🔺 VMA longue : 5 × 1000m à allure 5 km\n"
                "- Récup : 2′ trot\n"
                "- Objectif : travailler la résistance à l’allure 5k"
            )
            warm = "15′ footing + 3 lignes droites progressives"
            cool = "10′ footing"

        else:  # fartlek
            main = (
                "🌪️ Fartlek : 8 × (1′ rapide / 1′ lent)\n"
                "- Phase rapide proche allure 3–5 km\n"
                "- Phase lente en footing\n"
                "- Laisse-toi guider par les sensations"
            )
            warm = "15′ footing facile"
            cool = "10′ footing + marche"

        return {
            "titre": "Entraînement du jour — RUN 🏃‍♂️",
            "warm": warm,
            "main": main,
            "cool": cool,
            "focus": "course à pied",
        }

    elif focus == "boxe":
        rounds = 6 if duration_min <= 45 else 8
        main_rounds = []

        themes_pool = [
            "Jab uniquement, contrôle de la distance",
            "Jab-cross, vitesse mains",
            "Travail au corps, séries courtes",
            "Esquives + contres",
            "Crochets au corps + au visage",
            "Uppercuts de près",
            "Gestion du ring, déplacements",
            "Travail en explosivité 10″ / 20″",
        ]

        for i in range(1, rounds + 1):
            theme = random.choice(themes_pool)
            main_rounds.append(f"Round {i} : {theme}")

        warm = "10′ corde à sauter + shadow boxing léger (2×3′)"
        main = (
            f"🥊 {rounds} × 3′ au sac ou en shadow avec thème par round :\n"
            "- " + "\n- ".join(main_rounds) +
            "\n\nRepos : 1′ entre les rounds.\nConcentre-toi sur la technique avant la puissance."
        )
        cool = "5–10′ shadow très léger + respiration + étirements des épaules/nuque"

        return {
            "titre": "Entraînement du jour — BOXE 🥊",
            "warm": warm,
            "main": main,
            "cool": cool,
            "focus": "boxe anglaise",
        }

    else:  # mix
        run_part = generate_edj(duration_min // 2, "run")
        boxe_part = generate_edj(duration_min - duration_min // 2, "boxe")

        warm = run_part["warm"]
        main = (
            "1️⃣ Partie RUN 🏃‍♂️\n"
            + run_part["main"]
            + "\n\n2️⃣ Partie BOXE 🥊\n"
            + boxe_part["main"]
        )
        cool = boxe_part["cool"]

        return {
            "titre": "Entraînement du jour — MIX RUN & BOXE",
            "warm": warm,
            "main": main,
            "cool": cool,
            "focus": "mixte",
        }


# ---------- COMMANDES DISCORD ----------

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="!help pour voir les commandes"))


@bot.command(name="vo2")
async def vo2_command(ctx, age: int, poids_kg: float, temps_5km: str):
    """
    Commande : !vo2 age poids_kg temps_5km
    Ex: !vo2 21 63 19:35
    """
    try:
        time_seconds = parse_time_to_seconds(temps_5km)
    except ValueError as e:
        await ctx.send(f"❌ {e}")
        return

    vo2 = estimate_vo2max_from_5k(time_seconds)
    vma = estimate_vma_from_5k(time_seconds)
    seuil_sec_per_km = threshold_pace_from_vma(vma)

    pace_5k_sec = time_seconds / 5.0

    t10k = riegel_predict_time(time_seconds, 5.0, 10.0)
    t21k = riegel_predict_time(time_seconds, 5.0, 21.097)

    embed = discord.Embed(
        title="🧠 Analyse 5 km & VO2max",
        description=f"Données pour **{age} ans**, **{poids_kg} kg**, **5 km en {temps_5km}**",
        color=0x00FF99,
    )

    embed.add_field(
        name="VO2max estimée",
        value=f"**{vo2:.1f} ml/kg/min**",
        inline=False,
    )

    embed.add_field(
        name="VMA estimée",
        value=f"**{vma:.1f} km/h**",
        inline=True,
    )

    embed.add_field(
        name="Allure moyenne 5 km",
        value=f"**{seconds_to_pace_min_km(pace_5k_sec)}**",
        inline=True,
    )

    embed.add_field(
        name="Allure seuil estimée",
        value=f"**{seconds_to_pace_min_km(seuil_sec_per_km)}**",
        inline=False,
    )

    embed.add_field(
        name="Prédiction 10 km",
        value=f"**{format_time(t10k)}**",
        inline=True,
    )

    embed.add_field(
        name="Prédiction semi-marathon",
        value=f"**{format_time(t21k)}**",
        inline=True,
    )

    embed.set_footer(text="Bot sportif by Mathis")

    await ctx.send(embed=embed)


@bot.command(name="edj")
async def edj_command(ctx, duree: int = 45, focus: str = "mix"):
    """
    Commande : !edj [duree_en_min] [focus]
    - duree (optionnel) : durée totale approximative (ex: 45)
    - focus (optionnel) : run / boxe / mix
    Exemples :
      !edj
      !edj 60
      !edj 40 run
      !edj 50 boxe
    """
    plan = generate_edj(duree, focus)

    embed = discord.Embed(
        title=plan["titre"],
        description=f"Durée cible : ~{duree} minutes\nFocus : **{plan['focus']}**",
        color=0x3498DB,
    )

    embed.add_field(
        name="🔥 Échauffement",
        value=plan["warm"],
        inline=False,
    )

    embed.add_field(
        name="🏋️ Bloc principal",
        value=plan["main"],
        inline=False,
    )

    embed.add_field(
        name="🧊 Retour au calme",
        value=plan["cool"],
        inline=False,
    )

    embed.set_footer(text="EDJ généré automatiquement — adapte selon tes sensations 🔁")

    await ctx.send(embed=embed)


@bot.command(name="help")
async def help_command(ctx):
    msg = (
        "🏃‍♂️ **Commandes dispo :**\n\n"
        "`!vo2 age poids_kg temps_5km`\n"
        "➡ Exemple : `!vo2 21 63 19:35`\n"
        "→ Donne VO2max estimée, VMA, allure seuil, prédiction 10k & semi.\n\n"
        "`!edj [duree] [focus]`\n"
        "➡ Exemple : `!edj`, `!edj 60`, `!edj 40 run`, `!edj 50 boxe`\n"
        "→ Génère un entraînement du jour (course, boxe ou mix)."
    )
    await ctx.send(msg)


# ---------- LANCEMENT DU BOT ----------

if __name__ == "__main__":
    bot.run(TOKEN)
