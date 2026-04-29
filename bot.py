# ======================================================
# BOT DE DISCORD - Pedidos, Eventos, Bienvenida y Gambling
# ======================================================
# Instalación: pip install discord.py flask aiosqlite
# Uso: python bot.py
# ======================================================

import discord
from discord.ext import commands, tasks
import asyncio
from flask import Flask, request, jsonify
import threading
import os
import random
import hmac
import aiosqlite
from datetime import date

# ══════════════════════════════════════════════════════
# CONFIGURACIÓN — Variables de entorno
# ══════════════════════════════════════════════════════

BOT_TOKEN           = os.getenv("BOT_TOKEN", "")
PORT                = int(os.getenv("PORT", "3000"))
CLAVE_SECRETA       = os.getenv("CLAVE_SECRETA", "")

def parse_ids(env_var, default=""):
    val = os.getenv(env_var, default).strip()
    if not val:
        return []
    return [i.strip() for i in val.split(",") if i.strip()]

MIEMBROS_A_NOTIFICAR = parse_ids("MIEMBROS_A_NOTIFICAR")
CANAL_EVENTOS_ID     = os.getenv("CANAL_EVENTOS_ID", "").strip()
CANAL_BIENVENIDA_ID  = os.getenv("CANAL_BIENVENIDA_ID", "").strip()
CANAL_PEDIDOS_ID     = os.getenv("CANAL_PEDIDOS_ID", "1422442183121829919").strip()
CANAL_GAMBLING_ID    = os.getenv("CANAL_GAMBLING_ID", "1494103294916690011").strip()
ROL_ADMIN            = os.getenv("ROL_ADMIN", "Admin")
FORM_PEDIDOS_URL     = "https://docs.google.com/forms/d/14LsVLEm1lHdQCeBMYDfzIwW-q2vrUP4kzGCo8MadJjA"

# ── Configuración de GG-Coins ──────────────────────────
COINS_POR_MENSAJE    = (2, 5)
COINS_POR_MINUTO_VOZ = 3
COINS_DAILY          = 100
DB_PATH              = "ggcoins.db"

# ══════════════════════════════════════════════════════
# BASE DE DATOS — aiosqlite (evita race conditions)
# ══════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id TEXT PRIMARY KEY,
                coins INTEGER DEFAULT 0,
                daily TEXT DEFAULT NULL
            )
        """)
        await db.commit()

async def get_coins(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT coins, daily FROM usuarios WHERE user_id = ?", (str(user_id),)) as cur:
            row = await cur.fetchone()
            if not row:
                await db.execute("INSERT INTO usuarios (user_id, coins) VALUES (?, 50)", (str(user_id),))
                await db.commit()
                return {"coins": 50, "daily": None}
            return {"coins": row[0], "daily": row[1]}

async def add_coins(user_id, cantidad):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO usuarios (user_id, coins) VALUES (?, MAX(0, ?))
            ON CONFLICT(user_id) DO UPDATE SET coins = MAX(0, coins + ?)
        """, (str(user_id), cantidad, cantidad))
        await db.commit()
        async with db.execute("SELECT coins FROM usuarios WHERE user_id = ?", (str(user_id),)) as cur:
            row = await cur.fetchone()
            return row[0]

async def set_daily(user_id, hoy):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO usuarios (user_id, daily) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET daily = ?
        """, (str(user_id), hoy, hoy))
        await db.commit()

async def get_top(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, coins FROM usuarios ORDER BY coins DESC LIMIT ?", (limit,)) as cur:
            return await cur.fetchall()

# ══════════════════════════════════════════════════════
# SETUP DEL BOT
# ══════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
app = Flask(__name__)
sesiones_evento = {}
sesiones_bj = {}

# ══════════════════════════════════════════════════════
# EVENTO: Bot listo
# ══════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await init_db()
    print(f"✅ Bot conectado como: {bot.user}")
    print(f"📡 Servidor HTTP escuchando en el puerto {PORT}")
    recompensar_voz.start()

# ══════════════════════════════════════════════════════
# TASK: Recompensar usuarios en canal de voz (cada minuto)
# ══════════════════════════════════════════════════════
@tasks.loop(minutes=1)
async def recompensar_voz():
    for guild in bot.guilds:
        for canal in guild.voice_channels:
            for member in canal.members:
                if not member.bot:
                    await add_coins(member.id, COINS_POR_MINUTO_VOZ)

# ══════════════════════════════════════════════════════
# EVENTO: Nuevo miembro
# ══════════════════════════════════════════════════════
@bot.event
async def on_member_join(member):
    try:
        await get_coins(member.id)  # inicializa con 50 coins
        if not CANAL_BIENVENIDA_ID:
            return
        canal = bot.get_channel(int(CANAL_BIENVENIDA_ID))
        if not canal:
            return
        embed = discord.Embed(
            title=f"👋 ¡Bienvenido al servidor, {member.name}!",
            description=(
                "Nos alegra tenerte aquí. Aquí te dejamos una guía rápida:\n\n"
                "📋 **¿Quieres hacer un pedido?**\n"
                "Escribe `!anotame` en el canal de pedidos.\n\n"
                "🎰 **¿Quieres jugar?**\n"
                "Tienes **50 GG-Coins** de bienvenida. Usa `!casino` para ver los juegos.\n\n"
                "📅 **¿Hay eventos próximos?**\n"
                "Revisa el canal de eventos.\n\n"
                "❓ **¿Tienes dudas?**\n"
                "Contacta a un administrador."
            ),
            color=0x5865f2
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="¡Esperamos que disfrutes tu estadía!")
        await canal.send(content=f"<@{member.id}>", embed=embed)
    except Exception as e:
        print(f"❌ Error enviando bienvenida: {e}")

# ══════════════════════════════════════════════════════
# EVENTO: Mensajes
# ══════════════════════════════════════════════════════
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    coins_ganadas = random.randint(*COINS_POR_MENSAJE)
    await add_coins(message.author.id, coins_ganadas)

    await bot.process_commands(message)

    user_id = message.author.id
    contenido = message.content.strip()

    if user_id in sesiones_evento:
        sesion = sesiones_evento[user_id]
        if contenido.lower() == "cancelar":
            del sesiones_evento[user_id]
            await message.reply("❌ Creación de evento cancelada.")
            return

        tipos = {
            "1": "🏆 Torneo", "2": "🎬 Noche de película",
            "3": "🃏 Sesión de práctica", "4": "🎁 Giveaway", "5": "🎉 Otro",
        }

        if sesion["paso"] == 1:
            if contenido not in tipos:
                await message.reply("Por favor responde con un número del 1 al 5.")
                return
            sesion["datos"]["tipo"] = tipos[contenido]
            sesion["paso"] = 2
            await message.reply("📅 **Crear nuevo evento** — Paso 2/4\n\n¿Cuál es la fecha y hora?\n_Ejemplo: 15/04/2026 a las 8:00 PM_")
        elif sesion["paso"] == 2:
            sesion["datos"]["fecha"] = contenido
            sesion["paso"] = 3
            await message.reply("📅 **Crear nuevo evento** — Paso 3/4\n\nEscribe una descripción:")
        elif sesion["paso"] == 3:
            sesion["datos"]["descripcion"] = contenido
            sesion["paso"] = 4
            await message.reply("📅 **Crear nuevo evento** — Paso 4/4\n\n¿Tienes un link?\n_Si no tienes, escribe `ninguno`._")
        elif sesion["paso"] == 4:
            sesion["datos"]["link"] = None if contenido.lower() == "ninguno" else contenido
            try:
                if CANAL_EVENTOS_ID:
                    canal_eventos = bot.get_channel(int(CANAL_EVENTOS_ID))
                    datos = sesion["datos"]
                    embed = discord.Embed(title=datos["tipo"], color=0xfee75c)
                    embed.add_field(name="📅 Fecha y hora", value=datos["fecha"], inline=False)
                    embed.add_field(name="📝 Descripción", value=datos["descripcion"], inline=False)
                    if datos["link"]:
                        embed.add_field(name="🔗 Link", value=datos["link"], inline=False)
                    embed.set_footer(text=f"Evento creado por {message.author.name}")
                    await canal_eventos.send(content="@everyone", embed=embed)
                    await message.reply("✅ ¡Evento publicado correctamente!")
            except Exception as e:
                await message.reply("❌ Hubo un error al publicar el evento.")
            del sesiones_evento[user_id]

    if user_id in sesiones_bj:
        await manejar_blackjack(message, contenido)

# ══════════════════════════════════════════════════════
# COMANDO: !anotame
# ══════════════════════════════════════════════════════
@bot.command(name="anotame")
async def anotame(ctx):
    if str(ctx.channel.id) != CANAL_PEDIDOS_ID:
        await ctx.reply("❌ Este comando solo funciona en el canal de pedidos.")
        return
    embed = discord.Embed(
        title="🃏 ¿Quieres hacer un pedido?",
        description=(
            "Rellena el formulario con los detalles de tu pedido:\n\n"
            f"📋 **[Haz clic aquí para abrir el formulario]({FORM_PEDIDOS_URL})**\n\n"
            "Una vez enviado, el equipo revisará tu pedido y te contactará para confirmar.\n\n"
            "⚠️ Recuerda que los pedidos **no son inmediatos** y requieren confirmación."
        ),
        color=0xeb459e
    )
    embed.set_footer(text="Bot de Pedidos — GG TCG")
    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# COMANDO: !evento
# ══════════════════════════════════════════════════════
@bot.command(name="evento")
async def evento(ctx):
    rol = discord.utils.get(ctx.guild.roles, name=ROL_ADMIN)
    if rol not in ctx.author.roles:
        await ctx.reply("❌ No tienes permiso para crear eventos.")
        return
    sesiones_evento[ctx.author.id] = {"paso": 1, "datos": {}}
    await ctx.reply(
        "📅 **Crear nuevo evento** — Paso 1/4\n\n"
        "¿Qué tipo de evento es?\n"
        "`1` 🏆 Torneo\n`2` 🎬 Noche de película\n`3` 🃏 Sesión de práctica\n"
        "`4` 🎁 Giveaway\n`5` 🎉 Otro\n\n_Responde con el número. Escribe `cancelar` para salir._"
    )

# ══════════════════════════════════════════════════════
# COMANDO: !coins
# ══════════════════════════════════════════════════════
@bot.command(name="coins")
async def coins(ctx):
    datos = await get_coins(ctx.author.id)
    embed = discord.Embed(
        title="💰 Tu saldo de GG-Coins",
        description=f"**{ctx.author.name}** tiene **{datos['coins']} GG-Coins** 🪙",
        color=0xf1c40f
    )
    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# COMANDO: !daily
# ══════════════════════════════════════════════════════
@bot.command(name="daily")
async def daily(ctx):
    datos = await get_coins(ctx.author.id)
    hoy = str(date.today())

    if datos["daily"] == hoy:
        embed = discord.Embed(
            title="⏰ Ya reclamaste tu daily",
            description="Vuelve mañana para reclamar tus **100 GG-Coins** diarias.",
            color=0xe74c3c
        )
        await ctx.reply(embed=embed)
        return

    await set_daily(ctx.author.id, hoy)
    nuevo_saldo = await add_coins(ctx.author.id, COINS_DAILY)
    embed = discord.Embed(
        title="🎁 ¡Daily reclamado!",
        description=f"Recibiste **{COINS_DAILY} GG-Coins** 🪙\nSaldo actual: **{nuevo_saldo} GG-Coins**",
        color=0x2ecc71
    )
    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# COMANDO: !casino
# ══════════════════════════════════════════════════════
@bot.command(name="casino")
async def casino(ctx):
    if str(ctx.channel.id) != CANAL_GAMBLING_ID:
        await ctx.reply("❌ Los juegos solo están disponibles en el canal de casino.")
        return
    datos = await get_coins(ctx.author.id)
    embed = discord.Embed(
        title="🎰 Casino GG-TCG",
        description=(
            f"Tienes **{datos['coins']} GG-Coins** 🪙\n\n"
            "**Juegos disponibles:**\n\n"
            "🃏 `!bj <apuesta>` — Blackjack\n"
            "🎰 `!slots <apuesta>` — Tragamonedas\n"
            "🔴 `!ruleta <color/número> <apuesta>` — Ruleta\n\n"
            "**Otros comandos:**\n"
            "💰 `!coins` — Ver tu saldo\n"
            "🎁 `!daily` — Bonus diario (100 coins)\n"
            "🏆 `!top` — Top 10 más ricos"
        ),
        color=0xf39c12
    )
    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# COMANDO: !top
# ══════════════════════════════════════════════════════
@bot.command(name="top")
async def top(ctx):
    ranking = await get_top(10)
    descripcion = ""
    medallas = ["🥇", "🥈", "🥉"]

    for i, (uid, coins_amt) in enumerate(ranking):
        medalla = medallas[i] if i < 3 else f"`{i+1}.`"
        usuario = bot.get_user(int(uid))
        if not usuario:
            try:
                usuario = await bot.fetch_user(int(uid))
            except:
                usuario = None
        nombre = usuario.name if usuario else f"Usuario {uid}"
        descripcion += f"{medalla} **{nombre}** — {coins_amt} GG-Coins\n"

    embed = discord.Embed(
        title="🏆 Top 10 GG-Coins",
        description=descripcion or "No hay datos aún.",
        color=0xf1c40f
    )
    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# JUEGO: SLOTS
# ══════════════════════════════════════════════════════
@bot.command(name="slots")
async def slots(ctx, apuesta: int = 0):
    if str(ctx.channel.id) != CANAL_GAMBLING_ID:
        await ctx.reply("❌ Los juegos solo están disponibles en el canal de casino.")
        return
    if apuesta < 5:
        await ctx.reply("❌ La apuesta mínima es **5 GG-Coins**.")
        return
    if apuesta > 200:
        await ctx.reply("❌ La apuesta máxima es **200 GG-Coins**.")
        return

    datos = await get_coins(ctx.author.id)
    if datos["coins"] < apuesta:
        await ctx.reply(f"❌ No tienes suficientes GG-Coins. Tienes **{datos['coins']}**.")
        return

    simbolos = ["🍒", "🍋", "🍊", "⭐", "💎", "7️⃣"]
    resultado = [random.choice(simbolos) for _ in range(3)]
    linea = " | ".join(resultado)

    if resultado[0] == resultado[1] == resultado[2]:
        if resultado[0] == "💎":
            multiplicador = 10
        elif resultado[0] == "7️⃣":
            multiplicador = 7
        elif resultado[0] == "⭐":
            multiplicador = 5
        else:
            multiplicador = 3
        ganancia = apuesta * multiplicador
        nuevo_saldo = await add_coins(ctx.author.id, ganancia - apuesta)
        embed = discord.Embed(
            title="🎰 ¡JACKPOT!",
            description=f"[ {linea} ]\n\n🎉 ¡Ganaste **{ganancia} GG-Coins**! (x{multiplicador})\nSaldo: **{nuevo_saldo} GG-Coins**",
            color=0x2ecc71
        )
    elif resultado[0] == resultado[1] or resultado[1] == resultado[2]:
        nuevo_saldo = datos["coins"]
        embed = discord.Embed(
            title="🎰 ¡Par!",
            description=f"[ {linea} ]\n\nRecuperas tu apuesta. Saldo: **{nuevo_saldo} GG-Coins**",
            color=0xf1c40f
        )
    else:
        nuevo_saldo = await add_coins(ctx.author.id, -apuesta)
        embed = discord.Embed(
            title="🎰 Sin suerte...",
            description=f"[ {linea} ]\n\nPerdiste **{apuesta} GG-Coins**. Saldo: **{nuevo_saldo} GG-Coins**",
            color=0xe74c3c
        )

    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# JUEGO: RULETA
# ══════════════════════════════════════════════════════
@bot.command(name="ruleta")
async def ruleta(ctx, apuesta_tipo: str = "", apuesta: int = 0):
    if str(ctx.channel.id) != CANAL_GAMBLING_ID:
        await ctx.reply("❌ Los juegos solo están disponibles en el canal de casino.")
        return
    if apuesta < 10:
        await ctx.reply("❌ La apuesta mínima es **10 GG-Coins**.\nUso: `!ruleta rojo 50` o `!ruleta 17 50`")
        return
    if apuesta > 500:
        await ctx.reply("❌ La apuesta máxima es **500 GG-Coins**.")
        return

    datos = await get_coins(ctx.author.id)
    if datos["coins"] < apuesta:
        await ctx.reply(f"❌ No tienes suficientes GG-Coins. Tienes **{datos['coins']}**.")
        return

    numero = random.randint(0, 36)
    rojos = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "🔴 Rojo" if numero in rojos else ("⚫ Negro" if numero != 0 else "🟢 Verde")

    apuesta_tipo = apuesta_tipo.lower()
    gano = False
    multiplicador = 1

    if apuesta_tipo == "rojo":
        gano = numero in rojos
        multiplicador = 2
    elif apuesta_tipo == "negro":
        gano = numero not in rojos and numero != 0
        multiplicador = 2
    elif apuesta_tipo == "par":
        gano = numero != 0 and numero % 2 == 0
        multiplicador = 2
    elif apuesta_tipo == "impar":
        gano = numero % 2 == 1
        multiplicador = 2
    elif apuesta_tipo.isdigit():
        gano = int(apuesta_tipo) == numero
        multiplicador = 35
    else:
        await ctx.reply("❌ Apuesta inválida. Opciones: `rojo`, `negro`, `par`, `impar`, o un número del 0 al 36.")
        return

    if gano:
        ganancia = apuesta * multiplicador
        nuevo_saldo = await add_coins(ctx.author.id, ganancia - apuesta)
        embed = discord.Embed(
            title="🎡 ¡Ruleta!",
            description=f"La bola cayó en **{numero}** {color}\n\n🎉 ¡Ganaste **{ganancia} GG-Coins**!\nSaldo: **{nuevo_saldo} GG-Coins**",
            color=0x2ecc71
        )
    else:
        nuevo_saldo = await add_coins(ctx.author.id, -apuesta)
        embed = discord.Embed(
            title="🎡 ¡Ruleta!",
            description=f"La bola cayó en **{numero}** {color}\n\nPerdiste **{apuesta} GG-Coins**. Saldo: **{nuevo_saldo} GG-Coins**",
            color=0xe74c3c
        )

    await ctx.reply(embed=embed)

# ══════════════════════════════════════════════════════
# JUEGO: BLACKJACK
# ══════════════════════════════════════════════════════
def crear_baraja():
    palos = ["♠", "♥", "♦", "♣"]
    valores = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    baraja = [f"{v}{p}" for p in palos for v in valores]
    random.shuffle(baraja)
    return baraja

def valor_carta(carta):
    v = carta[:-1]
    if v in ["J", "Q", "K"]: return 10
    if v == "A": return 11
    return int(v)

def calcular_mano(mano):
    total = sum(valor_carta(c) for c in mano)
    ases = sum(1 for c in mano if c[:-1] == "A")
    while total > 21 and ases:
        total -= 10
        ases -= 1
    return total

def mostrar_mano(mano):
    return " ".join(mano)

@bot.command(name="bj")
async def blackjack(ctx, apuesta: int = 0):
    if str(ctx.channel.id) != CANAL_GAMBLING_ID:
        await ctx.reply("❌ Los juegos solo están disponibles en el canal de casino.")
        return
    if apuesta < 10:
        await ctx.reply("❌ La apuesta mínima es **10 GG-Coins**.")
        return
    if apuesta > 500:
        await ctx.reply("❌ La apuesta máxima es **500 GG-Coins**.")
        return
    if ctx.author.id in sesiones_bj:
        await ctx.reply("❌ Ya tienes una partida en curso. Escribe `pedir` o `plantarse`.")
        return

    datos = await get_coins(ctx.author.id)
    if datos["coins"] < apuesta:
        await ctx.reply(f"❌ No tienes suficientes GG-Coins. Tienes **{datos['coins']}**.")
        return

    baraja = crear_baraja()
    mano_jugador = [baraja.pop(), baraja.pop()]
    mano_dealer = [baraja.pop(), baraja.pop()]

    sesiones_bj[ctx.author.id] = {
        "apuesta": apuesta,
        "baraja": baraja,
        "jugador": mano_jugador,
        "dealer": mano_dealer,
    }

    total_jugador = calcular_mano(mano_jugador)
    embed = discord.Embed(title="🃏 Blackjack", color=0x2c3e50)
    embed.add_field(name="Tu mano", value=f"{mostrar_mano(mano_jugador)} — **{total_jugador}**", inline=False)
    embed.add_field(name="Dealer", value=f"{mano_dealer[0]} 🂠", inline=False)
    embed.add_field(name="Apuesta", value=f"**{apuesta} GG-Coins**", inline=False)
    embed.set_footer(text="Escribe 'pedir' para otra carta o 'plantarse' para terminar.")

    if total_jugador == 21:
        await ctx.reply(embed=embed)
        await terminar_blackjack(ctx, ctx.author.id, "blackjack")
    else:
        await ctx.reply(embed=embed)

async def manejar_blackjack(message, contenido):
    user_id = message.author.id
    if user_id not in sesiones_bj:
        return
    if str(message.channel.id) != CANAL_GAMBLING_ID:
        return

    sesion = sesiones_bj[user_id]

    if contenido.lower() == "pedir":
        sesion["jugador"].append(sesion["baraja"].pop())
        total = calcular_mano(sesion["jugador"])

        embed = discord.Embed(title="🃏 Blackjack", color=0x2c3e50)
        embed.add_field(name="Tu mano", value=f"{mostrar_mano(sesion['jugador'])} — **{total}**", inline=False)
        embed.add_field(name="Dealer", value=f"{sesion['dealer'][0]} 🂠", inline=False)

        if total > 21:
            await message.reply(embed=embed)
            await terminar_blackjack(message, user_id, "bust")
        elif total == 21:
            await message.reply(embed=embed)
            await terminar_blackjack(message, user_id, "plantarse")
        else:
            embed.set_footer(text="Escribe 'pedir' para otra carta o 'plantarse' para terminar.")
            await message.reply(embed=embed)

    elif contenido.lower() == "plantarse":
        await terminar_blackjack(message, user_id, "plantarse")

async def terminar_blackjack(ctx_or_msg, user_id, motivo):
    sesion = sesiones_bj.pop(user_id, None)
    if not sesion:
        return

    apuesta = sesion["apuesta"]
    jugador = sesion["jugador"]
    dealer = sesion["dealer"]
    baraja = sesion["baraja"]
    total_jugador = calcular_mano(jugador)

    while calcular_mano(dealer) < 17:
        dealer.append(baraja.pop())
    total_dealer = calcular_mano(dealer)

    embed = discord.Embed(title="🃏 Resultado — Blackjack", color=0x2c3e50)
    embed.add_field(name="Tu mano", value=f"{mostrar_mano(jugador)} — **{total_jugador}**", inline=False)
    embed.add_field(name="Dealer", value=f"{mostrar_mano(dealer)} — **{total_dealer}**", inline=False)

    if motivo == "bust":
        nuevo_saldo = await add_coins(user_id, -apuesta)
        embed.add_field(name="Resultado", value=f"💥 ¡Te pasaste! Perdiste **{apuesta} GG-Coins**.\nSaldo: **{nuevo_saldo}**", inline=False)
        embed.color = 0xe74c3c
    elif motivo == "blackjack" and len(jugador) == 2:
        ganancia = int(apuesta * 1.5)
        nuevo_saldo = await add_coins(user_id, ganancia)
        embed.add_field(name="Resultado", value=f"🎉 ¡BLACKJACK! Ganaste **{ganancia} GG-Coins**.\nSaldo: **{nuevo_saldo}**", inline=False)
        embed.color = 0x2ecc71
    elif total_dealer > 21 or total_jugador > total_dealer:
        nuevo_saldo = await add_coins(user_id, apuesta)
        embed.add_field(name="Resultado", value=f"🎉 ¡Ganaste **{apuesta} GG-Coins**!\nSaldo: **{nuevo_saldo}**", inline=False)
        embed.color = 0x2ecc71
    elif total_jugador == total_dealer:
        datos = await get_coins(user_id)
        embed.add_field(name="Resultado", value=f"🤝 Empate. Recuperas tu apuesta.\nSaldo: **{datos['coins']}**", inline=False)
        embed.color = 0xf1c40f
    else:
        nuevo_saldo = await add_coins(user_id, -apuesta)
        embed.add_field(name="Resultado", value=f"😞 Perdiste **{apuesta} GG-Coins**.\nSaldo: **{nuevo_saldo}**", inline=False)
        embed.color = 0xe74c3c

    if hasattr(ctx_or_msg, 'reply'):
        await ctx_or_msg.reply(embed=embed)

# ══════════════════════════════════════════════════════
# ENDPOINT HTTP: Recibir pedido desde Google Apps Script
# ══════════════════════════════════════════════════════
@app.route("/nuevo-pedido", methods=["POST"])
def nuevo_pedido():
    data = request.json or {}
    secreto = data.get("secreto", "")

    if not hmac.compare_digest(secreto, CLAVE_SECRETA):
        return jsonify({"error": "No autorizado"}), 401

    nombre = data.get("nombre", "—")
    fecha  = data.get("fecha", "—")

    if not nombre or not fecha:
        return jsonify({"error": "Faltan campos obligatorios"}), 400

    discord_user = data.get("discord", "—")
    correo       = data.get("correo", "—")
    carta        = data.get("carta", "—")
    set_col      = data.get("set", "—")
    rareza       = data.get("rareza", "—")
    cantidad     = data.get("cantidad", "—")
    link         = data.get("link", "")
    precio       = data.get("precio", "—")
    lista        = data.get("lista", "")

    print(f"\n📦 Nuevo pedido recibido de: {nombre}")

    asyncio.run_coroutine_threadsafe(
        enviar_dms(nombre, discord_user, correo, carta, set_col, rareza, cantidad, link, precio, lista, fecha),
        bot.loop
    )

    return jsonify({"ok": True})

async def enviar_dms(nombre, discord_user, correo, carta, set_col, rareza, cantidad, link, precio, lista, fecha):
    embed = discord.Embed(title="📦 ¡Nuevo pedido recibido!", color=0xed4245)
    embed.add_field(name="👤 Nombre / Nickname", value=nombre, inline=True)
    embed.add_field(name="🎮 Usuario de Discord", value=discord_user, inline=True)
    embed.add_field(name="📧 Correo", value=correo, inline=False)
    embed.add_field(name="🃏 Carta / Producto", value=carta, inline=True)
    embed.add_field(name="📦 Set / Colección", value=set_col, inline=True)
    embed.add_field(name="⭐ Rareza", value=rareza, inline=True)
    embed.add_field(name="🔢 Cantidad", value=cantidad, inline=True)
    embed.add_field(name="💰 Precio Estimado", value=precio, inline=True)
    embed.add_field(name="📅 Fecha", value=fecha, inline=False)
    if lista:
        embed.add_field(name="📋 Lista de cartas adicionales", value=lista, inline=False)
    if link:
        embed.add_field(name="🔗 Link de referencia", value=link, inline=False)
    embed.set_footer(text="Sistema de pedidos automático")

    for user_id in MIEMBROS_A_NOTIFICAR:
        try:
            usuario = await bot.fetch_user(int(user_id))
            await usuario.send(embed=embed)
            print(f"   ✉️  DM enviado a: {usuario}")
        except Exception as e:
            print(f"   ❌ Error enviando a {user_id}: {e}")

# ══════════════════════════════════════════════════════
# ARRANCAR
# ══════════════════════════════════════════════════════
def run_flask():
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Servidor HTTP escuchando en http://localhost:{PORT}")
    bot.run(BOT_TOKEN)
