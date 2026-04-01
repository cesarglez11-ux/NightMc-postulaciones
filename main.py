import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
import asyncio
import io
import re
import time
from datetime import datetime, timezone
from collections import defaultdict
import aiohttp
import os
from dotenv import load_dotenv

# ══════════════════════════════════════════════════════════════════
#  ⚙️  CONFIGURACIÓN  —  solo edita esta sección
# ══════════════════════════════════════════════════════════════════
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

ID_ROL_GESTION    = 1487582913200394260
ID_ROL_PREMIUM    = 1487595630888226976
ID_ROL_NO_PREMIUM = 1487595695048491079
ID_ROL_VERIFICADO = 1487582662276419676

ID_CATEGORIA_STATS = 1487544239050068163
ID_LOG_TICKETS     = 1487580312509747251
ID_LOG_APPEALS     = 1487620834398048306
ID_LOG_MOD         = 1487620834398048306
CANAL_BIENVENIDA   = 1487557353573322882
TICKET_CATEGORY    = "🎫 TICKETS NIGHTMC"

MC_HOST              = "tu.servidor.net"
MC_PORT              = 25565
MC_STATUS_CHANNEL_ID = 0   # pon el ID del canal aquí, o usa /mcstatus_setup

AUTOMOD_ENABLED = True
SPAM_THRESHOLD  = 5
SPAM_WINDOW     = 5
WARN_LIMIT      = 3
LINK_WHITELIST  = ["discord.gg/nightmc"]
BAD_WORDS: list[str] = []

RAID_THRESHOLD = 8
RAID_WINDOW    = 15

C_GREEN  = 0x57F287
C_RED    = 0xED4245
C_GOLD   = 0xFEE75C
C_DARK   = 0x2B2D31
C_PURPLE = 0x9B59B6
C_BLUE   = 0x5865F2

# ══════════════════════════════════════════════════════════════════
#  🤖  BOT
# ══════════════════════════════════════════════════════════════════
class NightBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketPanel())
        self.add_view(TicketControl())
        self.add_view(VerifView())
        self.add_view(TicketTypeView())
        self.add_view(RolePanel())
        await self.tree.sync()
        self.stats_loop.start()
        self.mc_loop.start()

    @tasks.loop(minutes=5)
    async def stats_loop(self):
        for guild in self.guilds:
            await update_stats(guild)

    @tasks.loop(minutes=2)
    async def mc_loop(self):
        for guild in self.guilds:
            await update_mc_status(guild)

    @stats_loop.before_loop
    @mc_loop.before_loop
    async def _wait(self):
        await self.wait_until_ready()

bot = NightBot()

# ══════════════════════════════════════════════════════════════════
#  🛠️  HELPERS
# ══════════════════════════════════════════════════════════════════
def is_gestion(member: discord.Member) -> bool:
    return any(r.id == ID_ROL_GESTION for r in member.roles)

def ts() -> str:
    return discord.utils.format_dt(datetime.now(timezone.utc), style="F")

def footer(embed: discord.Embed, text: str = "NightMC Network") -> discord.Embed:
    embed.set_footer(text=text, icon_url="https://i.imgur.com/4M7IWwP.png")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

# ══════════════════════════════════════════════════════════════════
#  📊  STATS
# ══════════════════════════════════════════════════════════════════
async def update_stats(guild: discord.Guild):
    cat = guild.get_channel(ID_CATEGORIA_STATS)
    if not cat:
        return
    humans = sum(1 for m in guild.members if not m.bot)
    bots   = sum(1 for m in guild.members if m.bot)
    desired = [
        ("Miembros", f"👥 ┃ Miembros: {humans}"),
        ("Bots",     f"🤖 ┃ Bots: {bots}"),
        ("Status",   f"🟢 ┃ Estado: Online"),
    ]
    for key, name in desired:
        found = next((c for c in cat.voice_channels if key in c.name), None)
        if not found:
            ch = await guild.create_voice_channel(name, category=cat)
            await ch.set_permissions(guild.default_role, connect=False, view_channel=True)
        elif found.name != name:
            await found.edit(name=name)

# ══════════════════════════════════════════════════════════════════
#  🌐  MINECRAFT
# ══════════════════════════════════════════════════════════════════
mc_status_channel_id: int = MC_STATUS_CHANNEL_ID
mc_status_message_id: int | None = None

async def query_mc() -> dict:
    url = f"https://api.mcsrvstat.us/3/{MC_HOST}:{MC_PORT}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception:
        pass
    return {}

async def build_mc_embed() -> discord.Embed:
    data   = await query_mc()
    online = data.get("online", False)
    if online:
        players  = data.get("players", {})
        current  = players.get("online", 0)
        maximum  = players.get("max", 0)
        version  = data.get("version", "?")
        motd_raw = data.get("motd", {}).get("clean", ["NightMC"])
        motd     = "\n".join(motd_raw) if isinstance(motd_raw, list) else motd_raw
        pl_list  = players.get("list", [])
        embed = discord.Embed(title="🟢  Servidor Online", description=f"```{motd}```", color=C_GREEN)
        embed.add_field(name="🌐 IP",        value=f"`{MC_HOST}`",            inline=True)
        embed.add_field(name="🎮 Versión",   value=f"`{version}`",            inline=True)
        embed.add_field(name="👥 Jugadores", value=f"`{current} / {maximum}`", inline=True)
        if pl_list:
            names = "\n".join(f"• {p['name']}" for p in pl_list[:20])
            if len(pl_list) > 20:
                names += f"\n… y {len(pl_list) - 20} más"
            embed.add_field(name="📋 Conectados ahora", value=names, inline=False)
        else:
            embed.add_field(name="📋 Conectados ahora", value="*(nadie o lista oculta)*", inline=False)
    else:
        embed = discord.Embed(
            title="🔴  Servidor Offline",
            description=f"No se pudo conectar a `{MC_HOST}:{MC_PORT}`",
            color=C_RED,
        )
    footer(embed, f"Se actualiza cada 2 min · {MC_HOST}")
    return embed

async def update_mc_status(guild: discord.Guild):
    global mc_status_message_id
    if not mc_status_channel_id:
        return
    channel = guild.get_channel(mc_status_channel_id)
    if not channel:
        return
    embed = await build_mc_embed()
    if mc_status_message_id:
        try:
            msg = await channel.fetch_message(mc_status_message_id)
            await msg.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException):
            mc_status_message_id = None
    async for msg in channel.history(limit=30):
        if msg.author == guild.me and msg.embeds:
            mc_status_message_id = msg.id
            await msg.edit(embed=embed)
            return
    new_msg = await channel.send(embed=embed)
    mc_status_message_id = new_msg.id

# ══════════════════════════════════════════════════════════════════
#  🎉  BIENVENIDA / SALIDA
# ══════════════════════════════════════════════════════════════════
@bot.event
async def on_member_join(member: discord.Member):
    await update_stats(member.guild)
    await antiraid_check(member)
    canal = member.guild.get_channel(CANAL_BIENVENIDA)
    if not canal:
        return
    try:
        user       = await bot.fetch_user(member.id)
        banner_url = user.banner.url if user.banner else None
    except Exception:
        banner_url = None
    embed = discord.Embed(
        title="🎉  ¡Bienvenido a NightMC Network!",
        description=f"Hola {member.mention}, revisa las reglas y ¡disfruta tu estancia! 🚀",
        color=C_GREEN,
    )
    embed.add_field(name="👤 Usuario",   value=str(member),                                           inline=True)
    embed.add_field(name="🆔 ID",        value=f"`{member.id}`",                                      inline=True)
    embed.add_field(name="📅 Cuenta",    value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
    embed.add_field(name="👥 Miembro #", value=f"`{member.guild.member_count}`",                      inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    if banner_url:
        embed.set_image(url=banner_url)
    footer(embed, "Sistema de bienvenida · NightMC")
    await canal.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    await update_stats(member.guild)
    canal = member.guild.get_channel(CANAL_BIENVENIDA)
    if not canal:
        return
    embed = discord.Embed(title="😢  Un miembro nos dejó", description=f"**{member}** ha salido del servidor.", color=C_RED)
    embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    footer(embed, "Sistema de salida · NightMC")
    await canal.send(embed=embed)

# ══════════════════════════════════════════════════════════════════
#  🪐  VERIFICACIÓN
# ══════════════════════════════════════════════════════════════════
class VerifModal(Modal, title="🪐  Verificación — NightMC"):
    nick = TextInput(label="Nick de Minecraft", placeholder="Ej: Steve123", min_length=3, max_length=16)
    premium = TextInput(label="¿Eres Premium? (si / no)", placeholder="Escribe: si   o   no", min_length=2, max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        member    = interaction.user
        guild     = interaction.guild
        respuesta = self.premium.value.strip().lower()
        es_premium = respuesta in ("si", "sí", "yes", "s", "y")

        roles: list[discord.Role] = []
        for rid in [ID_ROL_VERIFICADO, ID_ROL_PREMIUM if es_premium else ID_ROL_NO_PREMIUM]:
            r = guild.get_role(rid)
            if r:
                roles.append(r)
        try:
            await member.add_roles(*roles, reason="Verificación NightMC")
        except discord.Forbidden:
            pass

        tipo = "⭐ Premium" if es_premium else "🆓 No Premium"
        embed = discord.Embed(title="✅  ¡Verificado!", description=f"Bienvenido, **{self.nick.value}**. Ya tienes acceso completo 🎉", color=C_GREEN)
        embed.add_field(name="🎮 Nick", value=self.nick.value, inline=True)
        embed.add_field(name="💎 Tipo", value=tipo,            inline=True)
        footer(embed, "NightMC · Verificación")
        await interaction.response.send_message(embed=embed, ephemeral=True)

        log = guild.get_channel(ID_LOG_APPEALS)
        if log:
            le = discord.Embed(title="📥  Nueva Verificación", color=C_PURPLE)
            le.add_field(name="👤 Usuario", value=f"{member} (`{member.id}`)", inline=False)
            le.add_field(name="🎮 Nick",    value=self.nick.value,             inline=True)
            le.add_field(name="💎 Premium", value=tipo,                        inline=True)
            le.set_thumbnail(url=member.display_avatar.url)
            footer(le, "NightMC · Log de Verificación")
            await log.send(embed=le)

class VerifView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚀  VERIFICARSE", style=discord.ButtonStyle.secondary, custom_id="verif_btn", emoji="🪐")
    async def v(self, interaction: discord.Interaction, button: Button):
        if any(r.id == ID_ROL_VERIFICADO for r in interaction.user.roles):
            return await interaction.response.send_message("✅ Ya estás verificado.", ephemeral=True)
        await interaction.response.send_modal(VerifModal())

# ══════════════════════════════════════════════════════════════════
#  🎨  PANEL DE ROLES
# ══════════════════════════════════════════════════════════════════
ROLE_OPTIONS: list[tuple[str, str, str, int]] = [
    ("pvp",      "⚔️",  "PvP",      0),
    ("survival", "🌲",  "Survival", 0),
    ("creativo", "🏗️",  "Creativo", 0),
    ("eventos",  "🎉",  "Eventos",  0),
    ("anuncios", "📢",  "Anuncios", 0),
    ("es",       "🇪🇸",  "Español",  0),
    ("en",       "🇬🇧",  "English",  0),
]

class RoleButton(Button):
    def __init__(self, suffix: str, emoji: str, label: str, role_id: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=label, emoji=emoji, custom_id=f"rolebtn_{suffix}")
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        if not self.role_id:
            return await interaction.response.send_message("⚠️ Rol sin ID configurado.", ephemeral=True)
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message("❌ Rol no encontrado.", ephemeral=True)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Panel de roles")
            await interaction.response.send_message(f"➖ Quitado: **{role.name}**", ephemeral=True)
        else:
            await interaction.user.add_roles(role, reason="Panel de roles")
            await interaction.response.send_message(f"✅ Dado: **{role.name}**", ephemeral=True)

class RolePanel(View):
    def __init__(self):
        super().__init__(timeout=None)
        for suffix, emoji, label, role_id in ROLE_OPTIONS:
            self.add_item(RoleButton(suffix, emoji, label, role_id))

# ══════════════════════════════════════════════════════════════════
#  🛡️  AUTOMOD
# ══════════════════════════════════════════════════════════════════
LINK_RE = re.compile(r"(https?://[^\s]+|discord\.gg/[^\s]+|www\.[^\s]+)", re.IGNORECASE)
spam_tracker: dict[int, list[float]] = defaultdict(list)
warn_tracker: dict[int, int]         = defaultdict(int)

async def mod_log(guild: discord.Guild, embed: discord.Embed):
    ch = guild.get_channel(ID_LOG_MOD)
    if ch:
        await ch.send(embed=embed)

async def warn_user(member: discord.Member, reason: str, msg: discord.Message | None = None):
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass
    warn_tracker[member.id] += 1
    w = warn_tracker[member.id]
    embed = discord.Embed(
        title="⚠️  Advertencia Automática",
        description=f"{member.mention} · **{reason}** · `{w}/{WARN_LIMIT}` warns",
        color=C_GOLD,
    )
    footer(embed, "NightMC · AutoMod")
    await mod_log(member.guild, embed)
    try:
        await member.send(embed=discord.Embed(description=f"⚠️ Advertencia en **{member.guild.name}**: {reason} (`{w}/{WARN_LIMIT}`)", color=C_GOLD))
    except Exception:
        pass
    if w >= WARN_LIMIT:
        try:
            await member.kick(reason=f"AutoMod: {WARN_LIMIT} warns")
            ke = discord.Embed(title="👢  Kick Automático", description=f"{member.mention} fue expulsado por {WARN_LIMIT} warns.", color=C_RED)
            footer(ke, "NightMC · AutoMod")
            await mod_log(member.guild, ke)
        except Exception:
            pass
        warn_tracker[member.id] = 0

@bot.event
async def on_message(message: discord.Message):
    if not AUTOMOD_ENABLED or message.author.bot or not message.guild:
        await bot.process_commands(message)
        return
    if is_gestion(message.author):
        await bot.process_commands(message)
        return

    now = time.time()
    uid = message.author.id
    spam_tracker[uid] = [t for t in spam_tracker[uid] if now - t < SPAM_WINDOW]
    spam_tracker[uid].append(now)
    if len(spam_tracker[uid]) >= SPAM_THRESHOLD:
        spam_tracker[uid] = []
        await warn_user(message.author, "Spam detectado", message)
        return

    if LINK_RE.search(message.content):
        if not any(w.lower() in message.content.lower() for w in LINK_WHITELIST):
            await warn_user(message.author, "Enlace no permitido", message)
            return

    lower = message.content.lower()
    for word in BAD_WORDS:
        if word.lower() in lower:
            await warn_user(message.author, "Palabra prohibida", message)
            return

    await bot.process_commands(message)

# ══════════════════════════════════════════════════════════════════
#  🚨  ANTI-RAID
# ══════════════════════════════════════════════════════════════════
lockdown_active = False
raid_joins: list[float] = []

async def antiraid_check(member: discord.Member):
    global lockdown_active
    now = time.time()
    raid_joins.append(now)
    raid_joins[:] = [t for t in raid_joins if now - t < RAID_WINDOW]
    if len(raid_joins) >= RAID_THRESHOLD and not lockdown_active:
        lockdown_active = True
        raid_joins.clear()
        guild   = member.guild
        log_ch  = guild.get_channel(ID_LOG_MOD)
        gestion = guild.get_role(ID_ROL_GESTION)
        embed = discord.Embed(
            title="🚨  RAID DETECTADO — LOCKDOWN ACTIVADO",
            description=f"**{RAID_THRESHOLD}+ entradas** en {RAID_WINDOW}s.\nUsa `/lockdown off` para desactivar.",
            color=C_RED,
        )
        footer(embed, "NightMC · Anti-Raid")
        for ch in guild.text_channels:
            try:
                await ch.set_permissions(guild.default_role, send_messages=False, reason="Anti-raid")
            except Exception:
                pass
        if log_ch:
            await log_ch.send(content=gestion.mention if gestion else "", embed=embed)
        await asyncio.sleep(600)
        if lockdown_active:
            await deactivate_lockdown(guild)

async def deactivate_lockdown(guild: discord.Guild):
    global lockdown_active
    lockdown_active = False
    for ch in guild.text_channels:
        try:
            await ch.set_permissions(guild.default_role, send_messages=None, reason="Lockdown desactivado")
        except Exception:
            pass
    log_ch = guild.get_channel(ID_LOG_MOD)
    if log_ch:
        embed = discord.Embed(title="✅  Lockdown Desactivado", description="El servidor volvió a la normalidad.", color=C_GREEN)
        footer(embed, "NightMC · Anti-Raid")
        await log_ch.send(embed=embed)

# ══════════════════════════════════════════════════════════════════
#  🎫  TICKETS
# ══════════════════════════════════════════════════════════════════
claimed: dict[int, int]      = {}
open_tickets: dict[int, int] = {}

class TicketTypeView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        cls=Select,
        custom_id="ticket_type_select",
        placeholder="📂 Selecciona el motivo de tu ticket…",
        options=[
            discord.SelectOption(label="🛠️  Soporte técnico",  value="soporte",   description="Problemas en el servidor de Minecraft"),
            discord.SelectOption(label="💰 Tienda / Compras",  value="tienda",    description="Problemas con pagos o rangos"),
            discord.SelectOption(label="⚖️  Apelación de ban", value="apelacion", description="Solicitar revisión de sanción"),
            discord.SelectOption(label="🤝 Postulación",       value="postular",  description="Aplicar a un cargo de staff"),
            discord.SelectOption(label="❓ Otro",              value="otro",      description="Cualquier otro asunto"),
        ],
        min_values=1, max_values=1,
    )
    async def select_type(self, interaction: discord.Interaction, select: Select):
        user   = interaction.user
        guild  = interaction.guild
        motivo = select.values[0]

        if user.id in open_tickets:
            ch = guild.get_channel(open_tickets[user.id])
            if ch:
                return await interaction.response.send_message(f"⚠️ Ya tienes un ticket: {ch.mention}", ephemeral=True)
            del open_tickets[user.id]

        cat = discord.utils.get(guild.categories, name=TICKET_CATEGORY)
        if not cat:
            cat = await guild.create_category(TICKET_CATEGORY)

        gestion_role = guild.get_role(ID_ROL_GESTION)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user:               discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if gestion_role:
            overwrites[gestion_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

        etiquetas = {
            "soporte":   ("🛠️", "Soporte Técnico"),
            "tienda":    ("💰", "Tienda / Compras"),
            "apelacion": ("⚖️", "Apelación de Ban"),
            "postular":  ("🤝", "Postulación"),
            "otro":      ("❓", "Otro"),
        }
        emoji, label = etiquetas.get(motivo, ("🎫", "Ticket"))

        channel = await guild.create_text_channel(
            name=f"{emoji}・{user.name}",
            category=cat,
            overwrites=overwrites,
            topic=f"Ticket de {user} | {label} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
        )
        open_tickets[user.id] = channel.id

        embed = discord.Embed(
            title=f"{emoji}  {label}",
            description=f"Hola {user.mention}, bienvenido a tu ticket.\nDescribe tu problema y el equipo te atenderá pronto.\n\n> ⚠️ No abandones el ticket sin resolver.",
            color=C_DARK,
        )
        embed.add_field(name="👤 Usuario",  value=user.mention, inline=True)
        embed.add_field(name="📂 Tipo",     value=label,         inline=True)
        embed.add_field(name="📅 Apertura", value=ts(),         inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        footer(embed, "NightMC · Sistema de Tickets")
        await channel.send(content=f"<@&{ID_ROL_GESTION}>", embed=embed, view=TicketControl())
        await interaction.response.send_message(f"✅ Ticket creado: {channel.mention}", ephemeral=True)

class TicketPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💥  ABRIR TICKET", style=discord.ButtonStyle.secondary, custom_id="open_ticket", emoji="🎫")
    async def open(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="📂  Selecciona el motivo", description="Elige la categoría que mejor describa tu consulta:", color=C_BLUE)
        footer(embed)
        await interaction.response.send_message(embed=embed, view=TicketTypeView(), ephemeral=True)

class TicketControl(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⚖️  RECLAMAR", style=discord.ButtonStyle.success, custom_id="claim_btn", row=0)
    async def claim(self, interaction: discord.Interaction, button: Button):
        if not is_gestion(interaction.user):
            return await interaction.response.send_message("❌ Solo gestión.", ephemeral=True)
        if interaction.channel.id in claimed:
            prev = interaction.guild.get_member(claimed[interaction.channel.id])
            return await interaction.response.send_message(f"⚠️ Ya reclamado por {prev.mention if prev else 'alguien'}.", ephemeral=True)
        claimed[interaction.channel.id] = interaction.user.id
        button.disabled = True
        button.label    = f"⚖️ Reclamado — {interaction.user.display_name}"
        embed = discord.Embed(title="🛡️  Ticket Reclamado", description=f"{interaction.user.mention} está atendiendo este ticket.", color=C_GOLD)
        footer(embed)
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="🔒  CERRAR", style=discord.ButtonStyle.danger, custom_id="close_btn", row=0)
    async def close(self, interaction: discord.Interaction, button: Button):
        if interaction.channel.id in claimed:
            if interaction.user.id != claimed[interaction.channel.id] and not is_gestion(interaction.user):
                return await interaction.response.send_message("❌ No puedes cerrar.", ephemeral=True)
        embed = discord.Embed(title="🔒  Cerrando Ticket", description=f"Cerrando en **5 segundos**. Cerrado por: {interaction.user.mention}", color=C_RED)
        footer(embed)
        await interaction.response.send_message(embed=embed)
        for uid, cid in list(open_tickets.items()):
            if cid == interaction.channel.id:
                del open_tickets[uid]
                break
        claimed.pop(interaction.channel.id, None)
        await log_close(interaction)
        await asyncio.sleep(5)
        await interaction.channel.delete()

    @discord.ui.button(label="📋  TRANSCRIPT", style=discord.ButtonStyle.secondary, custom_id="transcript_btn", row=0)
    async def transcript_btn(self, interaction: discord.Interaction, button: Button):
        if not is_gestion(interaction.user):
            return await interaction.response.send_message("❌ Solo gestión.", ephemeral=True)
        await interaction.response.send_message("📋 Generando…", ephemeral=True)
        await interaction.followup.send(file=await build_transcript(interaction.channel), ephemeral=True)

async def build_transcript(channel: discord.TextChannel) -> discord.File:
    lines = [
        "╔══════════════════════════════════════╗",
        f"  TRANSCRIPT — {channel.name}",
        f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "╚══════════════════════════════════════╝\n",
    ]
    async for m in channel.history(limit=None, oldest_first=True):
        t    = m.created_at.strftime("%H:%M:%S")
        kind = "[BOT]" if m.author.bot else "[USR]"
        lines.append(f"[{t}] {kind} {m.author} » {m.content or '(sin texto)'}")
        for att in m.attachments:
            lines.append(f"         📎 {att.url}")
    return discord.File(io.BytesIO("\n".join(lines).encode()), filename=f"transcript-{channel.name}.txt")

async def log_close(interaction: discord.Interaction):
    log = interaction.guild.get_channel(ID_LOG_TICKETS)
    if not log:
        return
    embed = discord.Embed(title="🔒  Ticket Cerrado", color=C_RED)
    embed.add_field(name="📁 Canal",        value=interaction.channel.name, inline=True)
    embed.add_field(name="👮 Cerrado por",  value=str(interaction.user),   inline=True)
    embed.add_field(name="📅 Fecha",        value=ts(),                    inline=False)
    footer(embed, "NightMC · Log de Tickets")
    await log.send(embed=embed, file=await build_transcript(interaction.channel))

# ══════════════════════════════════════════════════════════════════
#  ⚡  SLASH COMMANDS
# ══════════════════════════════════════════════════════════════════
tree = bot.tree

@tree.command(name="panel_tickets", description="Envía el panel de tickets")
@discord.app_commands.checks.has_permissions(administrator=True)
async def sl_panel_tickets(interaction: discord.Interaction):
    embed = discord.Embed(title="🎫  Centro de Soporte — NightMC", description="¿Necesitas ayuda? Abre un ticket y el equipo te atenderá.\n\n**📌 Antes de abrir un ticket:**\n> • Lee las reglas del servidor.\n> • Sé claro y detallado en tu consulta.", color=C_DARK)
    footer(embed, "NightMC Network · Soporte 24/7")
    await interaction.channel.send(embed=embed, view=TicketPanel())
    await interaction.response.send_message("✅ Panel enviado.", ephemeral=True)

@tree.command(name="panel_verificacion", description="Envía el panel de verificación")
@discord.app_commands.checks.has_permissions(administrator=True)
async def sl_panel_verif(interaction: discord.Interaction):
    embed = discord.Embed(title="🪐  Verificación — NightMC Network", description="Verifica tu cuenta para acceder al servidor.\n\n**📋 Pasos:**\n> 1. Presiona **🚀 VERIFICARSE**.\n> 2. Ingresa tu nick de Minecraft.\n> 3. Indica si eres Premium.\n> 4. ¡Listo! Acceso instantáneo.", color=C_PURPLE)
    footer(embed, "NightMC Network · Verificación")
    await interaction.channel.send(embed=embed, view=VerifView())
    await interaction.response.send_message("✅ Panel enviado.", ephemeral=True)

@tree.command(name="panel_roles", description="Envía el panel de roles")
@discord.app_commands.checks.has_permissions(administrator=True)
async def sl_panel_roles(interaction: discord.Interaction):
    embed = discord.Embed(title="🎨  Elige tus roles", description="Haz clic en un botón para obtener o quitar ese rol.", color=C_BLUE)
    footer(embed, "NightMC · Panel de Roles")
    await interaction.channel.send(embed=embed, view=RolePanel())
    await interaction.response.send_message("✅ Panel enviado.", ephemeral=True)

@tree.command(name="mcstatus", description="Ver el estado del servidor MC ahora")
async def sl_mcstatus(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=await build_mc_embed(), ephemeral=True)

@tree.command(name="mcstatus_setup", description="Configura el canal de estado del MC")
@discord.app_commands.describe(canal="Canal donde se publicará el estado")
@discord.app_commands.checks.has_permissions(administrator=True)
async def sl_mcstatus_setup(interaction: discord.Interaction, canal: discord.TextChannel):
    global mc_status_channel_id, mc_status_message_id
    mc_status_channel_id = canal.id
    mc_status_message_id = None
    await interaction.response.send_message(f"✅ Estado del MC en {canal.mention} cada 2 minutos.", ephemeral=True)
    await update_mc_status(interaction.guild)

@tree.command(name="lockdown", description="Activar o desactivar el lockdown")
@discord.app_commands.describe(accion="'on' para activar, 'off' para desactivar")
@discord.app_commands.checks.has_permissions(administrator=True)
async def sl_lockdown(interaction: discord.Interaction, accion: str):
    global lockdown_active
    guild = interaction.guild
    if accion.lower() == "on":
        lockdown_active = True
        for ch in guild.text_channels:
            try:
                await ch.set_permissions(guild.default_role, send_messages=False, reason="Lockdown manual")
            except Exception:
                pass
        embed = discord.Embed(title="🔒  Lockdown Activado", description="Canales bloqueados.", color=C_RED)
        footer(embed)
        await interaction.response.send_message(embed=embed)
    elif accion.lower() == "off":
        await deactivate_lockdown(guild)
        await interaction.response.send_message("✅ Lockdown desactivado.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Usa `on` o `off`.", ephemeral=True)

@tree.command(name="warn", description="Advertir a un usuario")
@discord.app_commands.describe(usuario="Usuario", razon="Motivo")
@discord.app_commands.checks.has_permissions(manage_messages=True)
async def sl_warn(interaction: discord.Interaction, usuario: discord.Member, razon: str = "No especificada"):
    await warn_user(usuario, razon)
    await interaction.response.send_message(f"⚠️ {usuario.mention} advertido. (`{warn_tracker[usuario.id]}/{WARN_LIMIT}`)", ephemeral=True)

@tree.command(name="warns", description="Ver advertencias de un usuario")
@discord.app_commands.describe(usuario="Usuario")
@discord.app_commands.checks.has_permissions(manage_messages=True)
async def sl_warns(interaction: discord.Interaction, usuario: discord.Member):
    await interaction.response.send_message(f"**{usuario}** tiene `{warn_tracker.get(usuario.id, 0)}/{WARN_LIMIT}` warns.", ephemeral=True)

@tree.command(name="clearwarns", description="Borrar advertencias de un usuario")
@discord.app_commands.describe(usuario="Usuario")
@discord.app_commands.checks.has_permissions(administrator=True)
async def sl_clearwarns(interaction: discord.Interaction, usuario: discord.Member):
    warn_tracker[usuario.id] = 0
    await interaction.response.send_message(f"✅ Warns de {usuario.mention} limpiados.", ephemeral=True)

@tree.command(name="aceptar", description="Aceptar verificación manualmente")
@discord.app_commands.describe(usuario="Usuario a aceptar")
@discord.app_commands.checks.has_permissions(manage_roles=True)
async def sl_aceptar(interaction: discord.Interaction, usuario: discord.Member):
    log = interaction.guild.get_channel(ID_LOG_APPEALS)
    embed = discord.Embed(title="✅  Verificación Aceptada", description=f"¡Felicidades {usuario.mention}! Tu solicitud fue aceptada. 🎉", color=C_GREEN)
    embed.add_field(name="👮 Revisado por", value=interaction.user.mention, inline=True)
    footer(embed)
    try:
        await usuario.send(embed=embed)
    except Exception:
        pass
    if log:
        await log.send(embed=embed)
    await interaction.response.send_message(embed=embed)

@tree.command(name="rechazar", description="Rechazar verificación manualmente")
@discord.app_commands.describe(usuario="Usuario", razon="Motivo")
@discord.app_commands.checks.has_permissions(manage_roles=True)
async def sl_rechazar(interaction: discord.Interaction, usuario: discord.Member, razon: str = "No especificada"):
    log = interaction.guild.get_channel(ID_LOG_APPEALS)
    embed = discord.Embed(title="❌  Verificación Rechazada", description=f"Lo sentimos {usuario.mention}, tu solicitud fue rechazada.", color=C_RED)
    embed.add_field(name="📌 Razón",        value=razon,                    inline=False)
    embed.add_field(name="👮 Revisado por", value=interaction.user.mention, inline=True)
    footer(embed)
    try:
        await usuario.send(embed=embed)
    except Exception:
        pass
    if log:
        await log.send(embed=embed)
    await interaction.response.send_message(embed=embed)

# ── Comandos de prefijo (compatibilidad) ──────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def panel_tickets(ctx: commands.Context):
    embed = discord.Embed(title="🎫  Centro de Soporte — NightMC", description="¿Necesitas ayuda? Abre un ticket y el equipo te atenderá.", color=C_DARK)
    footer(embed, "NightMC Network · Soporte 24/7")
    await ctx.send(embed=embed, view=TicketPanel())
    await ctx.message.delete()

@bot.command()
@commands.has_permissions(administrator=True)
async def panel_verificacion(ctx: commands.Context):
    embed = discord.Embed(title="🪐  Verificación — NightMC Network", description="Verifica tu cuenta para acceder al servidor.\n\n**📋 Pasos:**\n> 1. Presiona **🚀 VERIFICARSE**.\n> 2. Ingresa tu nick y si eres Premium.\n> 3. ¡Listo!", color=C_PURPLE)
    footer(embed, "NightMC Network · Verificación")
    await ctx.send(embed=embed, view=VerifView())
    await ctx.message.delete()

@bot.command()
async def claim(ctx: commands.Context):
    if not is_gestion(ctx.author):
        return await ctx.send("❌ Sin permisos.", delete_after=5)
    claimed[ctx.channel.id] = ctx.author.id
    embed = discord.Embed(title="🛡️  Ticket Reclamado", description=f"{ctx.author.mention} está atendiendo este ticket.", color=C_GOLD)
    footer(embed)
    await ctx.send(embed=embed)

@bot.command()
async def close(ctx: commands.Context):
    if ctx.channel.id in claimed:
        if ctx.author.id != claimed[ctx.channel.id] and not is_gestion(ctx.author):
            return await ctx.send("❌ Sin permisos.", delete_after=5)
    for uid, cid in list(open_tickets.items()):
        if cid == ctx.channel.id:
            del open_tickets[uid]
            break
    claimed.pop(ctx.channel.id, None)
    await log_close(ctx)
    await ctx.channel.delete()

@bot.command()
@commands.has_permissions(manage_roles=True)
async def aceptar(ctx: commands.Context, user: discord.Member):
    log = ctx.guild.get_channel(ID_LOG_APPEALS)
    embed = discord.Embed(title="✅  Verificación Aceptada", description=f"¡Felicidades {user.mention}! Bienvenido a NightMC 🎉", color=C_GREEN)
    embed.add_field(name="👮 Revisado por", value=ctx.author.mention, inline=True)
    footer(embed)
    try:
        await user.send(embed=embed)
    except Exception:
        pass
    if log:
        await log.send(embed=embed)
    await ctx.send(embed=embed)
    await ctx.message.delete()

@bot.command()
@commands.has_permissions(manage_roles=True)
async def rechazar(ctx: commands.Context, user: discord.Member, *, razon: str = "No especificada"):
    log = ctx.guild.get_channel(ID_LOG_APPEALS)
    embed = discord.Embed(title="❌  Verificación Rechazada", description=f"Lo sentimos {user.mention}, tu solicitud fue rechazada.", color=C_RED)
    embed.add_field(name="📌 Razón",        value=razon,              inline=False)
    embed.add_field(name="👮 Revisado por", value=ctx.author.mention, inline=True)
    footer(embed)
    try:
        await user.send(embed=embed)
    except Exception:
        pass
    if log:
        await log.send(embed=embed)
    await ctx.send(embed=embed)
    await ctx.message.delete()

# ══════════════════════════════════════════════════════════════════
#  🪵  EVENTOS
# ══════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados")
    except Exception as e:
        print(f"❌ Error al sincronizar: {e}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="NightMC Network 🌙"),
        status=discord.Status.online,
    )
    print(f"✅ {bot.user} online — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Sin permisos.", delete_after=5)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuario no encontrado.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Faltan argumentos.", delete_after=5)
    else:
        raise error

@tree.error
async def on_slash_error(interaction: discord.Interaction, error):
    msg = "❌ Sin permisos." if isinstance(error, discord.app_commands.MissingPermissions) else f"❌ {error}"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

# ══════════════════════════════════════════════════════════════════
#  🚀  ARRANQUE
# ══════════════════════════════════════════════════════════════════
bot.run(TOKEN)
