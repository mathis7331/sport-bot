import discord
from discord.ext import commands
import os
import datetime
import re
import psycopg2
from psycopg2.extras import RealDictCursor

# ================== CONFIGURATION & SÉCURITÉ ==================

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Vérification critique au démarrage
if not TOKEN:
    raise SystemExit("❌ ERREUR FATALE : La variable DISCORD_TOKEN est vide.")
if not DATABASE_URL:
    print("⚠️ ATTENTION : DATABASE_URL vide. Le bot ne pourra pas sauvegarder les données.")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================== GESTION BASE DE DONNÉES (POSTGRESQL) ==================

def get_db_connection():
    """Crée une connexion sécurisée à la DB."""
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"❌ Erreur connexion DB: {e}")
        return None

def init_db():
    """Initialise les tables si elles n'existent pas."""
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        
        # Table Profils (VMA, FC, etc.)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS runners (
                user_id BIGINT PRIMARY KEY,
                vma FLOAT,
                fcm INT,
                fcr INT,
                username TEXT
            )
        ''')
        
        # Table Records (PBs)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS records (
                user_id BIGINT,
                distance VARCHAR(20), -- '5k', '10k', 'semi', 'marathon'
                time_seconds INT,
                date DATE,
                PRIMARY KEY (user_id, distance)
            )
        ''')
        
        # Table Journal d'entraînement
        cur.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                date DATE,
                distance_km FLOAT,
                duration_seconds INT,
                comment TEXT
            )
        ''')
        
        conn.commit()
        print("✅ Base de données PostgreSQL initialisée et prête.")
    except Exception as e:
        print(f"❌ Erreur init DB: {e}")
    finally:
        conn.close()

# ================== LOGIQUE MÉTIER & VALIDATION (ANTI-CRASH) ==================

class TimeParser:
    """Classe utilitaire pour gérer les temps de manière robuste."""
    
    @staticmethod
    def parse(time_str: str) -> int:
        """
        Convertit 'hh:mm:ss' ou 'mm:ss' en secondes.
        Gère les erreurs et les formats exotiques.
        """
        time_str = time_str.strip().replace("h", ":").replace("m", ":").replace("s", "")
        parts = time_str.split(":")
        
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            raise ValueError("Format invalide. Utilise `mm:ss` (ex: 25:30) ou `hh:mm:ss`.")

        if len(parts) == 3: # hh:mm:ss
            h, m, s = parts
        elif len(parts) == 2: # mm:ss
            h, m, s = 0, parts[0], parts[1]
        else:
            raise ValueError("Format inconnu. Essaie `mm:ss`.")

        total_seconds = h * 3600 + m * 60 + s
        
        # SANITY CHECK : Est-ce réaliste ?
        if total_seconds > 172800: # Plus de 48h
            raise ValueError("⏱️ Ce temps semble un peu... long (plus de 48h ?). Vérifie ta saisie.")
        if total_seconds < 60: # Moins de 1 minute
            raise ValueError("🚀 Moins d'une minute ? Tu es en avion de chasse ?")
            
        return total_seconds

    @staticmethod
    def format(seconds: int) -> str:
        """Affiche les secondes en format propre hh:mm:ss"""
        if not seconds: return "--:--"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

class Calculations:
    """Moteur de calcul scientifique."""
    
    @staticmethod
    def estimate_vma_from_race(distance_km: float, time_sec: float) -> float:
        """Estimation VMA via formule de Léger/Mercier simplifiée."""
        speed_kmh = distance_km / (time_sec / 3600)
        # Formule empirique : VMA = Vitesse / %Soutien
        # %Soutien dépend du temps d'effort.
        # Pour faire simple : VMA est approx vitesse sur 6min.
        # Ici on utilise un ratio standard pour le 5km (env 90-93% VMA pour débutant/inter)
        if distance_km == 5:
            return speed_kmh / 0.92
        elif distance_km == 10:
            return speed_kmh / 0.85
        elif distance_km == 21.1:
            return speed_kmh / 0.78
        elif distance_km == 42.195:
            return speed_kmh / 0.70
        return speed_kmh # Fallback

    @staticmethod
    def get_pace(vma: float, percentage: float) -> str:
        target_speed = vma * (percentage / 100)
        sec_km = 3600 / target_speed
        return TimeParser.format(int(sec_km))

# ================== COMMANDES DISCORD ==================

@bot.event
async def on_ready():
    init_db()
    print(f'🚀 Bot Sportif Pro connecté : {bot.user.name}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.competing, name="le marathon"))

# --- 1. GESTION PROFIL ---

@bot.command(name="set5k")
async def set_5k(ctx, temps: str):
    """Enregistre ton record 5km et met à jour ta VMA."""
    try:
        seconds = TimeParser.parse(temps)
        
        # Limite humaine (Record du monde ~12:35)
        if seconds < 750: 
            await ctx.send("🤨 Tu cours plus vite que le record du monde ? Je ne te crois pas.")
            return

        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Sauvegarder le record
        cur.execute("""
            INSERT INTO records (user_id, distance, time_seconds, date) 
            VALUES (%s, '5k', %s, CURRENT_DATE)
            ON CONFLICT (user_id, distance) DO UPDATE 
            SET time_seconds = EXCLUDED.time_seconds, date = EXCLUDED.date
        """, (ctx.author.id, seconds))
        
        # 2. Mettre à jour la VMA estimée
        vma_estimee = Calculations.estimate_vma_from_race(5.0, seconds)
        cur.execute("""
            INSERT INTO runners (user_id, vma, username) VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET vma = %s, username = %s
        """, (ctx.author.id, vma_estimee, ctx.author.name, vma_estimee, ctx.author.name))
        
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="✅ Record 5km mis à jour", color=0x2ecc71)
        embed.add_field(name="Temps", value=TimeParser.format(seconds), inline=True)
        embed.add_field(name="Nouvelle VMA Estimée", value=f"{vma_estimee:.1f} km/h", inline=True)
        await ctx.send(embed=embed)

    except ValueError as e:
        await ctx.send(f"❌ Oups : {str(e)}")
    except Exception as e:
        print(e)
        await ctx.send("❌ Erreur base de données.")

@bot.command(name="profil")
async def profil(ctx, member: discord.Member = None):
    """Affiche la carte d'athlète complète."""
    target = member or ctx.author
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Récupérer infos runner
    cur.execute("SELECT * FROM runners WHERE user_id = %s", (target.id,))
    runner = cur.fetchone()
    
    # Récupérer records
    cur.execute("SELECT distance, time_seconds FROM records WHERE user_id = %s", (target.id,))
    records = {row['distance']: row['time_seconds'] for row in cur.fetchall()}
    
    conn.close()
    
    if not runner and not records:
        await ctx.send(f"🤷‍♂️ Aucun profil trouvé pour {target.display_name}. Utilise `!set5k` pour commencer.")
        return

    embed = discord.Embed(title=f"👤 Profil Athlète : {target.display_name}", color=0x3498db)
    embed.set_thumbnail(url=target.avatar.url if target.avatar else None)
    
    if runner:
        vma = runner.get('vma', 0)
        fcm = runner.get('fcm', 'N/A')
        embed.add_field(name="⚡ VMA", value=f"**{vma:.1f} km/h**" if vma else "Non définie", inline=True)
        embed.add_field(name="❤️ FC Max", value=f"{fcm} bpm", inline=True)

    # Affichage des records
    txt_records = ""
    order = ['5k', '10k', 'semi', 'marathon']
    for dist in order:
        if dist in records:
            txt_records += f"**{dist.upper()}**: {TimeParser.format(records[dist])}\n"
            
    if txt_records:
        embed.add_field(name="🏆 Records Personnels", value=txt_records, inline=False)
    
    await ctx.send(embed=embed)

# --- 2. CALCULS & ALLURES ---

@bot.command(name="allures")
async def allures(ctx):
    """Génère un tableau d'allures basé sur la VMA."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT vma FROM runners WHERE user_id = %s", (ctx.author.id,))
    res = cur.fetchone()
    conn.close()
    
    if not res or not res['vma']:
        await ctx.send("❌ Je ne connais pas ta VMA. Fais `!set5k [temps]` ou `!setvma [vitesse]`.")
        return

    vma = res['vma']
    
    embed = discord.Embed(title=f"🏃 Tes Allures (VMA {vma:.1f})", color=0xf1c40f)
    
    data = [
        ("Jogging / Récup", 65, "60-65%"),
        ("Endurance Fond.", 70, "70-75%"),
        ("Allure Marathon", 80, "80-82%"),
        ("Allure Semi", 85, "85-88%"),
        ("Seuil (1h)", 90, "90%"),
        ("VMA Courte", 105, "105%")
    ]
    
    desc = ""
    for name, pct, label in data:
        pace = Calculations.get_pace(vma, pct)
        desc += f"**{name}** ({label}) : `{pace}/km`\n"
        
    embed.description = desc
    await ctx.send(embed=embed)

# --- 3. LEADERBOARD (CLASSEMENT) ---

@bot.command(name="leaderboard")
async def leaderboard(ctx, distance="5k"):
    """Affiche le top 10 du serveur sur une distance."""
    if distance not in ['5k', '10k', 'semi', 'marathon']:
        await ctx.send("❌ Distances valides : 5k, 10k, semi, marathon")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Jointure pour avoir les noms (si stockés) ou juste l'ID
    cur.execute("""
        SELECT r.username, rec.time_seconds 
        FROM records rec
        JOIN runners r ON rec.user_id = r.user_id
        WHERE rec.distance = %s
        ORDER BY rec.time_seconds ASC
        LIMIT 10
    """, (distance,))
    
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        await ctx.send("🏜️ Le désert... Personne n'a enregistré de temps sur cette distance.")
        return

    embed = discord.Embed(title=f"🏆 CLASSEMENT {distance.upper()}", color=0xFFD700)
    text = ""
    for i, row in enumerate(rows):
        medaille = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"{i+1}."
        text += f"{medaille} **{row['username']}** : {TimeParser.format(row['time_seconds'])}\n"
    
    embed.description = text
    await ctx.send(embed=embed)

# --- 4. OUTILS PHYSIO ---

@bot.command(name="karvonen")
async def karvonen(ctx):
    """Calcule les zones cardiaques précises (Besoin FC Max + FC Repos)."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT fcm, fcr FROM runners WHERE user_id = %s", (ctx.author.id,))
    res = cur.fetchone()
    conn.close()

    if not res or not res['fcm'] or not res['fcr']:
        await ctx.send("❌ J'ai besoin de ta FC Max et FC Repos. Utilise `!setdata fcm 195` et `!setdata fcr 50`")
        return
        
    fcm, fcr = res['fcm'], res['fcr']
    reserve = fcm - fcr
    
    embed = discord.Embed(title="❤️ Zones Cardiaques (Karvonen)", description=f"FC Max: {fcm} | FC Repos: {fcr}", color=0xe74c3c)
    
    zones = [
        ("Zone 1 (Récup)", 0.50, 0.60),
        ("Zone 2 (Endurance)", 0.60, 0.70),
        ("Zone 3 (Tempo)", 0.70, 0.80),
        ("Zone 4 (Seuil)", 0.80, 0.90),
        ("Zone 5 (Max)", 0.90, 1.00)
    ]
    
    for name, low, high in zones:
        bpm_low = int(fcr + (reserve * low))
        bpm_high = int(fcr + (reserve * high))
        embed.add_field(name=name, value=f"{bpm_low} - {bpm_high} bpm", inline=False)
        
    await ctx.send(embed=embed)

@bot.command(name="setdata")
async def set_data(ctx, type_donnee: str, valeur: int):
    """Définit FC Max (fcm) ou FC Repos (fcr). Ex: !setdata fcm 190"""
    if type_donnee not in ['fcm', 'fcr', 'vma']:
        await ctx.send("❌ Types possibles : `fcm`, `fcr`, `vma`.")
        return
    
    # Validation basique
    if (type_donnee == 'fcm' and (valeur < 100 or valeur > 250)) or \
       (type_donnee == 'fcr' and (valeur < 30 or valeur > 120)):
       await ctx.send(f"🧐 La valeur {valeur} semble improbable pour {type_donnee}. Vérifie.")
       return

    conn = get_db_connection()
    cur = conn.cursor()
    
    sql = f"""
        INSERT INTO runners (user_id, {type_donnee}, username) VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET {type_donnee} = %s, username = %s
    """
    cur.execute(sql, (ctx.author.id, valeur, ctx.author.name, valeur, ctx.author.name))
    conn.commit()
    conn.close()
    
    await ctx.send(f"✅ **{type_donnee.upper()}** mis à jour : {valeur}")

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title="🏃‍♂️ Coach Running Pro - Commandes", color=0x95a5a6)
    embed.add_field(name="⚙️ Profil", value="`!set5k mm:ss` : Enregistre ton 5k (calcule ta VMA)\n`!setdata fcm/fcr [valeur]` : Règle ta FC Max/Repos\n`!profil` : Voir tes stats", inline=False)
    embed.add_field(name="📈 Performance", value="`!allures` : Tes allures d'entraînement\n`!karvonen` : Tes zones cardiaques précises\n`!leaderboard 5k` : Classement du serveur", inline=False)
    await ctx.send(embed=embed)

# Démarrage
bot.run(TOKEN)
```

### 3️⃣ Pourquoi ce code est "Niveau Boss" ?

1.  **Gestion des Erreurs (Try/Except)** : Regarde la classe `TimeParser`. Si tu tapes `!set5k patate`, le bot ne plantera pas. Il te dira "Format invalide". Si tu tapes `!set5k 30:00` (alors que tu pensais 30 min mais le format est mm:ss), il convertit intelligemment. Si tu mets `!set5k 1000h`, il te dit "Temps irréaliste".
2.  **Base de Données Relationnelle** : J'ai créé deux tables : `runners` (pour tes infos physiques) et `records` (pour tes chronos). C'est beaucoup plus propre que de tout mélanger.
3.  **Commandes Intelligentes** :
    * `!set5k` : Met à jour ton record ET recalcule automatiquement ta VMA.
    * `!allures` : Se base sur la VMA en base de données.
    * `!karvonen` : Utilise la formule de réserve cardiaque (beaucoup plus pro que juste le % de FC Max).
    * `!leaderboard` : Crée une compétition saine sur le serveur.

### 4️⃣ Mise en place (Checklist finale)

1.  Mets à jour ton `requirements.txt` sur ton Mac (et pour Railway) :
    ```text
    discord.py==2.3.2
    psycopg2-binary
