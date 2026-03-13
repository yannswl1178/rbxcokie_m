import discord
from discord.ext import commands
from discord import app_commands
import os
import sys
import datetime
import asyncio
import io
import json
import re
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 配置區域
# ============================================================

# Bot Token（從環境變數讀取）
TOKEN = os.getenv("DISCORD_TOKEN", "")

# ============================================================
# 身分組 ID
# ============================================================
ADMIN_ROLE_ID = 1479780178069815447       # 管理員身分組
AGENT_ROLE_ID = 1479780213599506463       # 代理身分組

# ============================================================
# 超級管理員（默認管理員）- 可在任何地方建立面板
# ============================================================
SUPER_ADMIN_IDS = [953263169307021322, 436350518512582656]

# ============================================================
# 系統一：商品目錄開單系統
# ============================================================
PRODUCT_CATEGORY_ID = 1480955984028631233       # 購買開單類別
PRODUCT_PANEL_CHANNEL_ID = 1480956021072466134  # 購買開單頻道（面板所在）

# ============================================================
# 系統二：洽群開單 / 意見單系統
# ============================================================
INQUIRY_CATEGORY_ID = 1481598319066087454       # 意見單類別
INQUIRY_PANEL_CHANNEL_ID = 1481598213281677424  # 意見單頻道（面板所在）

# ============================================================
# 商品列表 - 從 products.json 載入
# ============================================================
PRODUCTS_FILE = "products.json"
PRODUCTS = []

# ============================================================
# 動態管理員列表 - 從 managers.json 載入
# { "guild_id": [user_id, user_id, ...] }
# ============================================================
MANAGERS_FILE = "managers.json"
GUILD_MANAGERS = {}

# ============================================================
# 伺服器配置 - 從 guild_config.json 載入
# { "guild_id": { "product_log_channel": id, "inquiry_log_channel": id,
#                  "product_category": id, "inquiry_category": id } }
# ============================================================
GUILD_CONFIG_FILE = "guild_config.json"
GUILD_CONFIG = {}


def load_products():
    """從 products.json 載入商品列表"""
    global PRODUCTS
    try:
        if os.path.exists(PRODUCTS_FILE):
            with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
                PRODUCTS = json.load(f)
                print(f"📦 已載入 {len(PRODUCTS)} 個商品")
        else:
            PRODUCTS = []
    except Exception as e:
        print(f"⚠️ 載入商品資料失敗: {e}")
        PRODUCTS = []


def save_products():
    """保存商品列表到 products.json"""
    try:
        with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
            json.dump(PRODUCTS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存商品資料失敗: {e}")


def load_managers():
    """從 managers.json 載入動態管理員列表"""
    global GUILD_MANAGERS
    try:
        if os.path.exists(MANAGERS_FILE):
            with open(MANAGERS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                # 確保 key 為 str，value 為 list[int]
                GUILD_MANAGERS = {str(k): [int(uid) for uid in v] for k, v in raw.items()}
                total = sum(len(v) for v in GUILD_MANAGERS.values())
                print(f"👥 已載入 {total} 個動態管理員（跨 {len(GUILD_MANAGERS)} 個伺服器）")
        else:
            GUILD_MANAGERS = {}
    except Exception as e:
        print(f"⚠️ 載入管理員資料失敗: {e}")
        GUILD_MANAGERS = {}


def save_managers():
    """保存動態管理員列表到 managers.json"""
    try:
        with open(MANAGERS_FILE, "w", encoding="utf-8") as f:
            json.dump(GUILD_MANAGERS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存管理員資料失敗: {e}")


def load_guild_config():
    """從 guild_config.json 載入伺服器配置"""
    global GUILD_CONFIG
    try:
        if os.path.exists(GUILD_CONFIG_FILE):
            with open(GUILD_CONFIG_FILE, "r", encoding="utf-8") as f:
                GUILD_CONFIG = json.load(f)
                print(f"⚙️ 已載入 {len(GUILD_CONFIG)} 個伺服器配置")
        else:
            GUILD_CONFIG = {}
    except Exception as e:
        print(f"⚠️ 載入伺服器配置失敗: {e}")
        GUILD_CONFIG = {}


def save_guild_config():
    """保存伺服器配置到 guild_config.json"""
    try:
        with open(GUILD_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(GUILD_CONFIG, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存伺服器配置失敗: {e}")


def get_guild_config(guild_id: int) -> dict:
    """取得伺服器配置，不存在則建立預設"""
    gid = str(guild_id)
    if gid not in GUILD_CONFIG:
        GUILD_CONFIG[gid] = {
            "product_log_channel": None,
            "inquiry_log_channel": None,
            "product_category": PRODUCT_CATEGORY_ID,
            "inquiry_category": INQUIRY_CATEGORY_ID,
        }
    return GUILD_CONFIG[gid]


# ============================================================
# 內存存儲
# ============================================================
# 工單資料: { channel_id: { ... } }
ticket_data = {}

# 已結單的頻道集合（防止重複結單）
closed_tickets = set()

# ============================================================
# Bot 初始化
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ============================================================
# 工具函數
# ============================================================

def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def is_admin(member: discord.Member) -> bool:
    """檢查是否為管理員（管理員身分組 或 代理身分組 或 動態管理員 或 超級管理員）"""
    # 超級管理員一定是管理員
    if is_super_admin(member.id):
        return True
    # 固定身分組
    if has_role(member, ADMIN_ROLE_ID) or has_role(member, AGENT_ROLE_ID):
        return True
    # 動態管理員（按伺服器）
    if member.guild:
        gid = str(member.guild.id)
        if gid in GUILD_MANAGERS and member.id in GUILD_MANAGERS[gid]:
            return True
    return False


def is_super_admin(user_id: int) -> bool:
    """檢查是否為超級管理員（默認管理員）"""
    return user_id in SUPER_ADMIN_IDS


def get_ticket_data(channel_id: int) -> dict:
    if channel_id not in ticket_data:
        ticket_data[channel_id] = {
            "price": None,
            "claimed_by": None,
            "claimed_name": None,
            "ticket_type": "未知",
            "ticket_info": "未知",
            "owner_id": None,
            "log_channel_id": None,
            "is_inquiry": False,
            "inquiry_items": [],
        }
    return ticket_data[channel_id]


# ============================================================
# 結單記錄保存（Embed + txt 附件）
# ============================================================

async def save_transcript(channel: discord.TextChannel, ticket_owner: discord.Member,
                          ticket_type: str, ticket_info: str,
                          price: str = None, claimed_by_name: str = None,
                          closer: discord.Member = None,
                          log_channel: discord.TextChannel = None):
    """保存聊天記錄 - 簡潔 Embed + txt 附件格式
    如果有指定 log_channel，則同時發送到結單記錄頻道"""
    messages = []
    async for msg in channel.history(limit=500, oldest_first=True):
        messages.append(msg)

    if not messages:
        return

    # 建立聊天記錄 txt 文件
    chat_lines = []
    for msg in messages:
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content if msg.content else "[嵌入訊息/附件]"
        if msg.attachments:
            attachments_text = " | ".join([att.url for att in msg.attachments])
            content += f"\n  附件: {attachments_text}"
        if msg.embeds and not msg.content:
            embed_texts = []
            for emb in msg.embeds:
                if emb.title:
                    embed_texts.append(f"[Embed: {emb.title}]")
                if emb.description:
                    embed_texts.append(emb.description[:100])
            content = " | ".join(embed_texts) if embed_texts else "[嵌入訊息]"
        chat_lines.append(f"[{timestamp}] {msg.author}: {content}")

    chat_text = "\n".join(chat_lines)

    # 建立簡潔的 Embed
    open_time = messages[0].created_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    transcript_embed = discord.Embed(
        title=f"📋 票單 #{channel.name} 聊天記錄",
        color=discord.Color.purple()
    )

    transcript_embed.add_field(
        name="",
        value=f"**開單者：**{ticket_owner.mention} (<@{ticket_owner.id}>)",
        inline=False
    )

    if claimed_by_name:
        transcript_embed.add_field(
            name="",
            value=f"**負責人：**{claimed_by_name}",
            inline=False
        )
    else:
        transcript_embed.add_field(
            name="",
            value="**負責人：**❌ 無人認領",
            inline=False
        )

    if closer:
        transcript_embed.add_field(
            name="",
            value=f"**結單者：**{closer.mention} (<@{closer.id}>)",
            inline=False
        )

    transcript_embed.add_field(
        name="",
        value=f"**開單時間：**{open_time}",
        inline=False
    )

    if price:
        transcript_embed.add_field(
            name="",
            value=f"**訂單金額：**{price}",
            inline=False
        )

    # 發送到工單頻道本身
    file_bytes = chat_text.encode("utf-8")
    txt_file = discord.File(
        io.BytesIO(file_bytes),
        filename=f"{channel.name}-log.txt"
    )
    await channel.send(embed=transcript_embed, file=txt_file)

    # 如果有指定結單記錄頻道，也發送一份到那裡
    if log_channel:
        try:
            file_bytes2 = chat_text.encode("utf-8")
            txt_file2 = discord.File(
                io.BytesIO(file_bytes2),
                filename=f"{channel.name}-log.txt"
            )
            await log_channel.send(embed=transcript_embed, file=txt_file2)
        except Exception as e:
            print(f"⚠️ 發送結單記錄到 {log_channel.id} 失敗: {e}")

    return chat_text


# ============================================================
# 設定金額 Modal
# ============================================================

class SetPriceModal(discord.ui.Modal, title="💰 設定訂單金額 | Set Order Price"):
    price_input = discord.ui.TextInput(
        label="訂單金額 (Order Price)",
        placeholder="例如: 1500 tokens",
        style=discord.TextStyle.short,
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可設定金額。", ephemeral=True)
            return

        channel = interaction.channel
        price_value = self.price_input.value
        data = get_ticket_data(channel.id)
        data["price"] = price_value

        price_embed = discord.Embed(
            title="💰 訂單金額已設定 | Price Set",
            description=(
                f"**金額: {price_value}**\n\n"
                f"設定者: {interaction.user.mention}\n"
                f"時間: <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=price_embed)


# ============================================================
# 洽群開單：新增購買物品/價格 Modal（僅管理員）
# ============================================================

class AddInquiryItemModal(discord.ui.Modal, title="🛒 新增購買物品 | Add Item"):
    item_name = discord.ui.TextInput(
        label="購買物品名稱 (Item Name)",
        placeholder="例如: 連點器 永久版",
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )
    item_price = discord.ui.TextInput(
        label="價格 (Price)",
        placeholder="例如: 1500 tokens",
        style=discord.TextStyle.short,
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return

        channel = interaction.channel
        data = get_ticket_data(channel.id)

        item = {
            "name": self.item_name.value,
            "price": self.item_price.value,
            "added_by": str(interaction.user),
            "added_at": int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        }
        data["inquiry_items"].append(item)

        # 更新訂單金額（累加所有物品價格）
        total = 0
        for it in data["inquiry_items"]:
            try:
                price_num = float(re.sub(r'[^\d.]', '', it["price"]))
                total += price_num
            except (ValueError, TypeError):
                pass
        if total > 0:
            data["price"] = f"{total:.0f} tokens"

        item_embed = discord.Embed(
            title="🛒 已新增購買物品 | Item Added",
            description=(
                f"**物品名稱:** {self.item_name.value}\n"
                f"**價格:** {self.item_price.value}\n\n"
                f"新增者: {interaction.user.mention}\n"
                f"時間: <t:{item['added_at']}:F>"
            ),
            color=discord.Color.green()
        )

        # 顯示所有已新增的物品
        if len(data["inquiry_items"]) > 1:
            items_text = ""
            for i, it in enumerate(data["inquiry_items"], 1):
                items_text += f"{i}. {it['name']} - {it['price']}\n"
            item_embed.add_field(name="📦 所有購買物品", value=items_text, inline=False)

        if data.get("price"):
            item_embed.add_field(name="💰 目前總金額", value=data["price"], inline=False)

        await interaction.response.send_message(embed=item_embed)


# ============================================================
# 管理員面板按鈕 View
# ============================================================

class AdminTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 設定金額 | Set Price", style=discord.ButtonStyle.primary, custom_id="set_price_btn")
    async def set_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return
        modal = SetPriceModal()
        await interaction.response.send_modal(modal)


class InquiryAdminView(discord.ui.View):
    """洽群開單管理員面板 - 包含設定金額和新增購買物品按鈕"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 設定金額 | Set Price", style=discord.ButtonStyle.primary, custom_id="inquiry_set_price_btn")
    async def set_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return
        modal = SetPriceModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🛒 新增購買物品/價格 | Add Item", style=discord.ButtonStyle.success, custom_id="inquiry_add_item_btn")
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return
        modal = AddInquiryItemModal()
        await interaction.response.send_modal(modal)


# ============================================================
# 員工領單按鈕
# ============================================================

class ClaimTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📋 負責此單", style=discord.ButtonStyle.success, custom_id="claim_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可認領工單。", ephemeral=True)
            return

        channel = interaction.channel
        data = get_ticket_data(channel.id)

        if data["claimed_by"]:
            await interaction.response.send_message(
                f"❌ 此工單已由 **{data['claimed_name']}** 認領。",
                ephemeral=True
            )
            return

        data["claimed_by"] = interaction.user.id
        data["claimed_name"] = interaction.user.display_name

        # 更新按鈕為已認領
        button.label = f"📋 負責人: {interaction.user.display_name}"
        button.style = discord.ButtonStyle.secondary
        button.disabled = True
        await interaction.response.edit_message(view=self)

        claim_embed = discord.Embed(
            title="✅ 工單已認領",
            description=(
                f"**負責人:** {interaction.user.mention}\n"
                f"**時間:** <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>"
            ),
            color=discord.Color.green()
        )
        await channel.send(embed=claim_embed)


# ============================================================
# 結單按鈕 View（兩次確認 - 僅管理員可結單）
# ============================================================

class CloseTicketView(discord.ui.View):
    """結單按鈕 - 第一次點擊（僅管理員可操作）"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 結單 | Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_first")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ 僅管理員可進行結單操作。",
                ephemeral=True
            )
            return

        if interaction.channel.id in closed_tickets:
            await interaction.response.send_message("❌ 此工單已經結單，請勿重複操作。", ephemeral=True)
            return

        data = get_ticket_data(interaction.channel.id)
        price_text = f"\n**💰 訂單金額: {data['price']}**" if data.get("price") else ""
        claimed_text = f"\n**👨‍💼 負責人: {data['claimed_name']}**" if data.get("claimed_name") else ""

        confirm_embed = discord.Embed(
            title="⚠️ 確認結單 | Confirm Close",
            description=(
                "你確定要結單嗎？此操作無法撤銷。\n\n"
                "**聊天記錄將會被保存。**"
                f"{price_text}{claimed_text}"
            ),
            color=discord.Color.orange()
        )
        confirm_view = ConfirmCloseView()
        await interaction.response.send_message(embed=confirm_embed, view=confirm_view)


class ConfirmCloseView(discord.ui.View):
    """結單確認 - 第二次確認"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 確認結單 | Confirm Close", style=discord.ButtonStyle.danger, custom_id="close_ticket_confirm")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ 僅管理員可進行結單操作。",
                ephemeral=True
            )
            return

        if interaction.channel.id in closed_tickets:
            await interaction.response.send_message("❌ 此工單已經結單，請勿重複操作。", ephemeral=True)
            return

        # 標記為已結單
        closed_tickets.add(interaction.channel.id)

        # 禁用所有按鈕
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        channel = interaction.channel
        guild = interaction.guild
        data = get_ticket_data(channel.id)

        ticket_type = data.get("ticket_type", "未知")
        ticket_info = data.get("ticket_info", "未知")
        price = data.get("price")
        claimed_by_name = data.get("claimed_name")
        is_inquiry = data.get("is_inquiry", False)

        # 從頻道主題解析
        if channel.topic:
            if "洽群工單" in channel.topic or "意見單" in channel.topic:
                ticket_type = "意見單 | Inquiry Ticket"
                is_inquiry = True
            elif "商品購買工單" in channel.topic:
                ticket_type = "商品購買 | Product Order"
                try:
                    product_name = channel.topic.split("product:")[1].split("|")[0].strip()
                    product = next((p for p in PRODUCTS if p["name"] == product_name), None)
                    if product:
                        ticket_info = f"商品: {product['name']} | 價格: {product['description']}"
                except (IndexError, StopIteration):
                    pass

        # 發送結單中提示
        closing_embed = discord.Embed(
            title="🔒 結單中... | Closing Ticket...",
            description="正在保存聊天記錄...",
            color=discord.Color.red()
        )
        await channel.send(embed=closing_embed)

        # 獲取工單擁有者
        ticket_owner = interaction.user
        if channel.topic:
            try:
                owner_id = int(channel.topic.split("owner:")[1].split("|")[0].strip())
                member = guild.get_member(owner_id)
                if member:
                    ticket_owner = member
            except (ValueError, IndexError):
                pass

        # 確定結單記錄頻道
        log_channel = None
        log_ch_id = data.get("log_channel_id")
        if log_ch_id:
            log_channel = guild.get_channel(log_ch_id)
        else:
            # 從伺服器配置中取得
            gconfig = get_guild_config(guild.id)
            if is_inquiry and gconfig.get("inquiry_log_channel"):
                log_channel = guild.get_channel(gconfig["inquiry_log_channel"])
            elif not is_inquiry and gconfig.get("product_log_channel"):
                log_channel = guild.get_channel(gconfig["product_log_channel"])

        # 保存聊天記錄
        await save_transcript(channel, ticket_owner, ticket_type, ticket_info,
                              price=price, claimed_by_name=claimed_by_name,
                              closer=interaction.user, log_channel=log_channel)

        # 清理內存
        if channel.id in ticket_data:
            del ticket_data[channel.id]

        await asyncio.sleep(3)
        await channel.delete(reason=f"工單結單 by {interaction.user}")

    @discord.ui.button(label="❌ 取消 | Cancel", style=discord.ButtonStyle.secondary, custom_id="close_ticket_cancel")
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("✅ 已取消結單。", ephemeral=True)
        self.stop()


# ============================================================
# 開單後發送管理員專用訊息
# ============================================================

async def send_admin_panel(channel: discord.TextChannel, guild: discord.Guild,
                           is_inquiry_ticket: bool = False):
    """在開單頻道發送管理員操作面板"""
    admin_role = guild.get_role(ADMIN_ROLE_ID)
    agent_role = guild.get_role(AGENT_ROLE_ID)

    # 發送領單訊息
    claim_embed = discord.Embed(
        title="📋 此單總負責人",
        description=(
            "此票單尚未有管理員負責。\n\n"
            "請點擊下方按鈕認領此票單。"
        ),
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    claim_view = ClaimTicketView()
    mention_parts = []
    if admin_role:
        mention_parts.append(admin_role.mention)
    if agent_role:
        mention_parts.append(agent_role.mention)
    mention_text = " ".join(mention_parts) if mention_parts else ""

    await channel.send(
        content=f"{mention_text} 新票單已建立！" if mention_text else "新票單已建立！",
        embed=claim_embed,
        view=claim_view
    )

    # 洽群工單：顯示設定金額 + 新增購買物品按鈕
    if is_inquiry_ticket:
        admin_embed = discord.Embed(
            title="⚙️ 管理員操作面板 | Admin Panel",
            description=(
                "**僅管理員可使用以下功能：**\n\n"
                "💰 **設定金額** - 設定此工單的訂單金額\n"
                "🛒 **新增購買物品/價格** - 新增客戶購買的物品和價格"
            ),
            color=discord.Color.blurple()
        )
        admin_embed.set_footer(text="僅管理員可操作")

        admin_view = InquiryAdminView()
        await channel.send(embed=admin_embed, view=admin_view)


# ============================================================
# 系統一：商品目錄開單系統
# ============================================================

class ProductSelectMenu(discord.ui.Select):
    def __init__(self):
        options = []
        for product in PRODUCTS:
            stock_text = ""
            if "stock" in product and product["stock"] is not None:
                if product["stock"] <= 0:
                    stock_text = " [缺貨]"
                else:
                    stock_text = f" [庫存:{product['stock']}]"
            desc = (product["description"][:90] + stock_text)[:100]
            options.append(
                discord.SelectOption(
                    label=product["name"],
                    description=desc,
                    value=product["name"],
                    emoji=product["display_emoji"]
                )
            )
        if not options:
            options.append(
                discord.SelectOption(
                    label="暫無商品",
                    description="請管理員使用 /add-product 新增商品",
                    value="__no_product__",
                    emoji="❌"
                )
            )
        super().__init__(
            placeholder="選擇商品查看詳情...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="product_select"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_name = self.values[0]
        if selected_name == "__no_product__":
            await interaction.response.send_message("❌ 目前沒有商品，請等待管理員新增商品。", ephemeral=True)
            return
        product = next((p for p in PRODUCTS if p["name"] == selected_name), None)

        if not product:
            await interaction.response.send_message("❌ 商品不存在。", ephemeral=True)
            return

        # 檢查庫存
        if "stock" in product and product["stock"] is not None and product["stock"] <= 0:
            await interaction.response.send_message(
                f"❌ **{product['name']}** 目前缺貨中，請稍後再試或聯繫管理員。",
                ephemeral=True
            )
            return

        guild = interaction.guild
        # 取得該伺服器的商品開單類別
        gconfig = get_guild_config(guild.id)
        cat_id = gconfig.get("product_category", PRODUCT_CATEGORY_ID)
        category = guild.get_channel(cat_id)

        if not category:
            await interaction.response.send_message("❌ 找不到開單類別，請聯繫管理員。", ephemeral=True)
            return

        existing = discord.utils.get(
            guild.text_channels,
            name=f"order-{interaction.user.name.lower().replace(' ', '-')}"
        )
        if existing:
            await interaction.response.send_message(
                f"❌ 你已經有一個開啟的工單: {existing.mention}\n請先結單後再開新單。",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        admin_role = guild.get_role(ADMIN_ROLE_ID)
        agent_role = guild.get_role(AGENT_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                manage_channels=True, manage_messages=True
            )
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            )
        if agent_role:
            overwrites[agent_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            )

        # 為動態管理員添加權限
        gid = str(guild.id)
        if gid in GUILD_MANAGERS:
            for mgr_id in GUILD_MANAGERS[gid]:
                mgr = guild.get_member(mgr_id)
                if mgr:
                    overwrites[mgr] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True,
                        attach_files=True, embed_links=True
                    )

        ticket_channel = await guild.create_text_channel(
            name=f"order-{interaction.user.name.lower().replace(' ', '-')}",
            category=category,
            overwrites=overwrites,
            topic=f"owner:{interaction.user.id} | product:{selected_name} | 商品購買工單"
        )

        data = get_ticket_data(ticket_channel.id)
        data["ticket_type"] = "商品購買 | Product Order"
        data["ticket_info"] = f"商品: {product['name']} | 價格: {product['description']}"
        data["owner_id"] = interaction.user.id
        data["is_inquiry"] = False
        # 設定結單記錄頻道
        if gconfig.get("product_log_channel"):
            data["log_channel_id"] = gconfig["product_log_channel"]

        price_text = "\n".join([f"• **{period}**: {price}" for period, price in product["prices"].items()])

        stock_info = ""
        if "stock" in product and product["stock"] is not None:
            stock_info = f"\n📦 **庫存:** {product['stock']}\n"

        ticket_embed = discord.Embed(
            title="🛒 商品購買工單 | Product Order",
            description=(
                f"歡迎 {interaction.user.mention}！\n\n"
                f"你選擇了以下商品：\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"**{product['display_emoji']} {product['name']}**\n"
                f"{product['details']}\n\n"
                f"**💰 價格方案 | Pricing:**\n{price_text}\n"
                f"{stock_info}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"**📋 開單資訊 | Ticket Info:**\n"
                f"• 開單者: {interaction.user.mention}\n"
                f"• 選擇商品: **{product['name']}**\n"
                f"• 開單時間: <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>\n\n"
                f"請告知您想購買的方案，工作人員將盡快為您服務！"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        ticket_embed.set_footer(text=f"工單 ID: {ticket_channel.id}")

        close_view = CloseTicketView()
        await ticket_channel.send(embed=ticket_embed, view=close_view)

        # 發送管理員面板
        await send_admin_panel(ticket_channel, guild, is_inquiry_ticket=False)

        await interaction.followup.send(
            f"✅ 已為您開單！請前往 {ticket_channel.mention} 查看。",
            ephemeral=True
        )


class ProductSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelectMenu())


# ============================================================
# 系統二：洽群開單 / 意見單系統
# ============================================================

class InquiryTicketView(discord.ui.View):
    """意見單開單按鈕"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📩 建立意見單 | Create Ticket",
        style=discord.ButtonStyle.primary,
        emoji="📩",
        custom_id="inquiry_ticket_btn"
    )
    async def inquiry_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        # 取得該伺服器的意見單類別
        gconfig = get_guild_config(guild.id)
        cat_id = gconfig.get("inquiry_category", INQUIRY_CATEGORY_ID)
        category = guild.get_channel(cat_id)

        if not category:
            await interaction.response.send_message("❌ 找不到意見單類別，請聯繫管理員。", ephemeral=True)
            return

        # 檢查是否已有開啟的意見單
        existing = discord.utils.get(
            guild.text_channels,
            name=f"inquiry-{interaction.user.name.lower().replace(' ', '-')}"
        )
        if existing:
            await interaction.response.send_message(
                f"❌ 你已經有一個開啟的意見單: {existing.mention}\n請先結單後再開新單。",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        admin_role = guild.get_role(ADMIN_ROLE_ID)
        agent_role = guild.get_role(AGENT_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                manage_channels=True, manage_messages=True
            )
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            )
        if agent_role:
            overwrites[agent_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            )

        # 為動態管理員添加權限
        gid = str(guild.id)
        if gid in GUILD_MANAGERS:
            for mgr_id in GUILD_MANAGERS[gid]:
                mgr = guild.get_member(mgr_id)
                if mgr:
                    overwrites[mgr] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True,
                        attach_files=True, embed_links=True
                    )

        ticket_channel = await guild.create_text_channel(
            name=f"inquiry-{interaction.user.name.lower().replace(' ', '-')}",
            category=category,
            overwrites=overwrites,
            topic=f"owner:{interaction.user.id} | 意見單 | 洽群工單"
        )

        data = get_ticket_data(ticket_channel.id)
        data["ticket_type"] = "意見單 | Inquiry Ticket"
        data["ticket_info"] = "意見單開單"
        data["owner_id"] = interaction.user.id
        data["is_inquiry"] = True
        # 設定結單記錄頻道
        if gconfig.get("inquiry_log_channel"):
            data["log_channel_id"] = gconfig["inquiry_log_channel"]

        ticket_embed = discord.Embed(
            title="📩 意見單 | Inquiry Ticket",
            description=(
                f"歡迎 {interaction.user.mention}！\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"**📋 開單資訊 | Ticket Info:**\n"
                f"• 開單者: {interaction.user.mention}\n"
                f"• 工單類型: **意見單**\n"
                f"• 開單時間: <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"請描述您的需求，管理員將盡快為您服務！"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        ticket_embed.set_footer(text=f"工單 ID: {ticket_channel.id}")

        close_view = CloseTicketView()
        await ticket_channel.send(embed=ticket_embed, view=close_view)

        # 意見單：含設定金額 + 新增購買物品按鈕
        await send_admin_panel(ticket_channel, guild, is_inquiry_ticket=True)

        await interaction.followup.send(
            f"✅ 已為您開單！請前往 {ticket_channel.mention} 查看。",
            ephemeral=True
        )


# ============================================================
# Bot Ready 事件
# ============================================================

@bot.event
async def on_ready():
    print(f"✅ Bot 已上線: {bot.user} (ID: {bot.user.id})")
    print(f"📡 已連接到 {len(bot.guilds)} 個伺服器")

    # 載入資料
    load_products()
    load_managers()
    load_guild_config()

    # 註冊持久化 View
    bot.add_view(ProductSelectView())
    bot.add_view(InquiryTicketView())
    bot.add_view(CloseTicketView())
    bot.add_view(ConfirmCloseView())
    bot.add_view(ClaimTicketView())
    bot.add_view(AdminTicketView())
    bot.add_view(InquiryAdminView())

    # 同步斜線命令
    try:
        for guild in bot.guilds:
            synced = await bot.tree.sync(guild=guild)
            print(f"🔄 已同步 {len(synced)} 個命令到伺服器: {guild.name}")
        global_synced = await bot.tree.sync()
        print(f"🌐 已同步 {len(global_synced)} 個全域命令")
    except Exception as e:
        print(f"⚠️ 同步命令失敗: {e}")

    print("🚀 Bot 準備就緒！")


# ============================================================
# 處理持久化按鈕交互（備用處理器）
# ============================================================

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id", "")

    # 洽群開單按鈕備用處理器
    if custom_id == "inquiry_add_item_btn":
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return
        modal = AddInquiryItemModal()
        await interaction.response.send_modal(modal)
        return

    if custom_id == "inquiry_set_price_btn":
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return
        modal = SetPriceModal()
        await interaction.response.send_modal(modal)
        return

    if custom_id == "set_price_btn":
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 僅管理員可使用此功能。", ephemeral=True)
            return
        modal = SetPriceModal()
        await interaction.response.send_modal(modal)
        return


# ============================================================
# 斜線命令：設置面板
# ============================================================

@bot.tree.command(name="setup-product", description="設置商品目錄面板 | Setup Product Catalog Panel")
@app_commands.default_permissions(administrator=True)
async def setup_product(interaction: discord.Interaction):
    """設置商品購買開單面板（限定在購買開單頻道使用）"""
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    if interaction.channel_id != PRODUCT_PANEL_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 請在 <#{PRODUCT_PANEL_CHANNEL_ID}> 頻道使用此命令。",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    embed = discord.Embed(
        title="🛒",
        description=(
            "**歡迎來到 1ynz. 商店！**\n\n"
            "瀏覽我們優質商品及各式服務。\n"
            "從下方下拉式選單中選擇已有現貨產品\n"
            "即可查看詳細的價格。\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**💳 ━ 接受的付款方式：**\n"
            "• 🪙 blade ball tokens (有問題請dm @1ynz.)"
        ),
        color=discord.Color.purple()
    )
    embed.set_footer(text="1ynz. | 台灣最強連點器")

    view = ProductSelectView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.followup.send("✅ 商品目錄面板已設置！", ephemeral=True)


@bot.tree.command(name="setup-inquiry", description="設置意見單面板 | Setup Inquiry Ticket Panel")
@app_commands.default_permissions(administrator=True)
async def setup_inquiry(interaction: discord.Interaction):
    """設置意見單/洽群開單面板（限定在意見單頻道使用）"""
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    if interaction.channel_id != INQUIRY_PANEL_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 請在 <#{INQUIRY_PANEL_CHANNEL_ID}> 頻道使用此命令。",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    embed = discord.Embed(
        title="📩 洽群開單 | 意見發送 Ticket",
        description=(
            "請點擊下方按鈕建立意見單\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "管理員將盡快為您服務！"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="連點器購買開單系統")

    view = InquiryTicketView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.followup.send("✅ 意見單面板已設置！", ephemeral=True)


# ============================================================
# 超級管理員特殊指令：可自訂類別、頻道、結單頻道建立面板
# ============================================================

@bot.tree.command(name="admin-setup-product", description="[超級管理員] 在指定類別和頻道建立商品面板")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    category_id="開單類別 ID",
    channel_id="面板發送的頻道 ID",
    log_channel_id="結單記錄頻道 ID（結單時聊天記錄會發送到此頻道）"
)
async def admin_setup_product(interaction: discord.Interaction, category_id: str, channel_id: str, log_channel_id: str):
    """超級管理員專用：可在任何頻道建立商品購買面板，並自訂開單類別和結單頻道"""
    if not is_super_admin(interaction.user.id):
        await interaction.response.send_message("❌ 僅超級管理員可使用此命令。", ephemeral=True)
        return

    try:
        cat_id = int(category_id)
        ch_id = int(channel_id)
        log_ch_id = int(log_channel_id)
    except ValueError:
        await interaction.response.send_message("❌ 請輸入有效的 ID（純數字）。", ephemeral=True)
        return

    guild = interaction.guild
    target_channel = guild.get_channel(ch_id)
    target_category = guild.get_channel(cat_id)
    target_log_channel = guild.get_channel(log_ch_id)

    if not target_channel:
        await interaction.response.send_message(f"❌ 找不到頻道 ID: {ch_id}", ephemeral=True)
        return
    if not target_category:
        await interaction.response.send_message(f"❌ 找不到類別 ID: {cat_id}", ephemeral=True)
        return
    if not target_log_channel:
        await interaction.response.send_message(f"❌ 找不到結單頻道 ID: {log_ch_id}", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # 更新伺服器配置
    gconfig = get_guild_config(guild.id)
    gconfig["product_category"] = cat_id
    gconfig["product_log_channel"] = log_ch_id
    save_guild_config()

    # 同時更新全域變數（向後兼容）
    global PRODUCT_CATEGORY_ID, PRODUCT_PANEL_CHANNEL_ID
    PRODUCT_CATEGORY_ID = cat_id
    PRODUCT_PANEL_CHANNEL_ID = ch_id

    embed = discord.Embed(
        title="🛒",
        description=(
            "**歡迎來到 1ynz. 商店！**\n\n"
            "瀏覽我們優質商品及各式服務。\n"
            "從下方下拉式選單中選擇已有現貨產品\n"
            "即可查看詳細的價格。\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**💳 ━ 接受的付款方式：**\n"
            "• 🪙 blade ball tokens (有問題請dm @1ynz.)"
        ),
        color=discord.Color.purple()
    )
    embed.set_footer(text="1ynz. | 台灣最強連點器")

    view = ProductSelectView()
    await target_channel.send(embed=embed, view=view)

    await interaction.followup.send(
        f"✅ 商品面板已建立！\n"
        f"• 面板頻道: <#{ch_id}>\n"
        f"• 開單類別: {target_category.name} (`{cat_id}`)\n"
        f"• 結單記錄頻道: <#{log_ch_id}>",
        ephemeral=True
    )


@bot.tree.command(name="admin-setup-inquiry", description="[超級管理員] 在指定類別和頻道建立意見單面板")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    category_id="意見單類別 ID",
    channel_id="面板發送的頻道 ID",
    log_channel_id="結單記錄頻道 ID（結單時聊天記錄會發送到此頻道）"
)
async def admin_setup_inquiry(interaction: discord.Interaction, category_id: str, channel_id: str, log_channel_id: str):
    """超級管理員專用：可在任何頻道建立意見單面板，並自訂開單類別和結單頻道"""
    if not is_super_admin(interaction.user.id):
        await interaction.response.send_message("❌ 僅超級管理員可使用此命令。", ephemeral=True)
        return

    try:
        cat_id = int(category_id)
        ch_id = int(channel_id)
        log_ch_id = int(log_channel_id)
    except ValueError:
        await interaction.response.send_message("❌ 請輸入有效的 ID（純數字）。", ephemeral=True)
        return

    guild = interaction.guild
    target_channel = guild.get_channel(ch_id)
    target_category = guild.get_channel(cat_id)
    target_log_channel = guild.get_channel(log_ch_id)

    if not target_channel:
        await interaction.response.send_message(f"❌ 找不到頻道 ID: {ch_id}", ephemeral=True)
        return
    if not target_category:
        await interaction.response.send_message(f"❌ 找不到類別 ID: {cat_id}", ephemeral=True)
        return
    if not target_log_channel:
        await interaction.response.send_message(f"❌ 找不到結單頻道 ID: {log_ch_id}", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # 更新伺服器配置
    gconfig = get_guild_config(guild.id)
    gconfig["inquiry_category"] = cat_id
    gconfig["inquiry_log_channel"] = log_ch_id
    save_guild_config()

    # 同時更新全域變數（向後兼容）
    global INQUIRY_CATEGORY_ID, INQUIRY_PANEL_CHANNEL_ID
    INQUIRY_CATEGORY_ID = cat_id
    INQUIRY_PANEL_CHANNEL_ID = ch_id

    embed = discord.Embed(
        title="📩 洽群開單 | 意見發送 Ticket",
        description=(
            "請點擊下方按鈕建立意見單\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "管理員將盡快為您服務！"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="連點器購買開單系統")

    view = InquiryTicketView()
    await target_channel.send(embed=embed, view=view)

    await interaction.followup.send(
        f"✅ 意見單面板已建立！\n"
        f"• 面板頻道: <#{ch_id}>\n"
        f"• 開單類別: {target_category.name} (`{cat_id}`)\n"
        f"• 結單記錄頻道: <#{log_ch_id}>",
        ephemeral=True
    )


# ============================================================
# 超級管理員：動態管理員管理指令
# ============================================================

@bot.tree.command(name="admin-add-manager", description="[超級管理員] 添加管理員到此伺服器")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user_id="要添加為管理員的用戶 ID"
)
async def admin_add_manager(interaction: discord.Interaction, user_id: str):
    """超級管理員專用：在當前伺服器添加動態管理員"""
    if not is_super_admin(interaction.user.id):
        await interaction.response.send_message("❌ 僅超級管理員可使用此命令。", ephemeral=True)
        return

    try:
        uid = int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ 請輸入有效的用戶 ID（純數字）。", ephemeral=True)
        return

    guild = interaction.guild
    gid = str(guild.id)

    # 檢查用戶是否存在於伺服器
    member = guild.get_member(uid)
    if not member:
        # 嘗試 fetch
        try:
            member = await guild.fetch_member(uid)
        except discord.NotFound:
            await interaction.response.send_message(f"❌ 在此伺服器中找不到用戶 ID: {uid}", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message(f"❌ 無法查詢用戶 ID: {uid}", ephemeral=True)
            return

    # 檢查是否已經是管理員
    if gid in GUILD_MANAGERS and uid in GUILD_MANAGERS[gid]:
        await interaction.response.send_message(
            f"❌ **{member.display_name}** (`{uid}`) 已經是此伺服器的管理員了。",
            ephemeral=True
        )
        return

    # 添加管理員
    if gid not in GUILD_MANAGERS:
        GUILD_MANAGERS[gid] = []
    GUILD_MANAGERS[gid].append(uid)
    save_managers()

    embed = discord.Embed(
        title="✅ 管理員已添加 | Manager Added",
        description=(
            f"**用戶:** {member.mention} (`{uid}`)\n"
            f"**伺服器:** {guild.name}\n"
            f"**添加者:** {interaction.user.mention}\n"
            f"**時間:** <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>\n\n"
            f"此用戶現在可以使用所有管理員功能：\n"
            f"• 管理工單（領單、結單）\n"
            f"• 設定金額、新增購買物品\n"
            f"• 商品管理（新增/移除/庫存）\n"
            f"• 同步/重整命令"
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="admin-remove-manager", description="[超級管理員] 移除此伺服器的管理員")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user_id="要移除管理員身份的用戶 ID"
)
async def admin_remove_manager(interaction: discord.Interaction, user_id: str):
    """超級管理員專用：移除當前伺服器的動態管理員"""
    if not is_super_admin(interaction.user.id):
        await interaction.response.send_message("❌ 僅超級管理員可使用此命令。", ephemeral=True)
        return

    try:
        uid = int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ 請輸入有效的用戶 ID（純數字）。", ephemeral=True)
        return

    guild = interaction.guild
    gid = str(guild.id)

    if gid not in GUILD_MANAGERS or uid not in GUILD_MANAGERS[gid]:
        await interaction.response.send_message(
            f"❌ 用戶 ID `{uid}` 不在此伺服器的管理員列表中。",
            ephemeral=True
        )
        return

    GUILD_MANAGERS[gid].remove(uid)
    if not GUILD_MANAGERS[gid]:
        del GUILD_MANAGERS[gid]
    save_managers()

    member = guild.get_member(uid)
    name_text = f"{member.mention} (`{uid}`)" if member else f"`{uid}`"

    embed = discord.Embed(
        title="✅ 管理員已移除 | Manager Removed",
        description=(
            f"**用戶:** {name_text}\n"
            f"**伺服器:** {guild.name}\n"
            f"**移除者:** {interaction.user.mention}\n"
            f"**時間:** <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>"
        ),
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="admin-list-managers", description="[超級管理員] 列出此伺服器的所有管理員")
@app_commands.default_permissions(administrator=True)
async def admin_list_managers(interaction: discord.Interaction):
    """超級管理員專用：列出當前伺服器的所有動態管理員"""
    if not is_super_admin(interaction.user.id):
        await interaction.response.send_message("❌ 僅超級管理員可使用此命令。", ephemeral=True)
        return

    guild = interaction.guild
    gid = str(guild.id)

    embed = discord.Embed(
        title=f"👥 管理員列表 | {guild.name}",
        color=discord.Color.blue()
    )

    # 超級管理員
    super_text = ""
    for sa_id in SUPER_ADMIN_IDS:
        member = guild.get_member(sa_id)
        if member:
            super_text += f"• {member.mention} (`{sa_id}`) 👑\n"
        else:
            super_text += f"• `{sa_id}` 👑 (不在此伺服器)\n"
    embed.add_field(name="👑 超級管理員", value=super_text or "無", inline=False)

    # 固定身分組
    admin_role = guild.get_role(ADMIN_ROLE_ID)
    agent_role = guild.get_role(AGENT_ROLE_ID)
    role_text = ""
    if admin_role:
        role_text += f"• {admin_role.mention} ({len(admin_role.members)} 人)\n"
    if agent_role:
        role_text += f"• {agent_role.mention} ({len(agent_role.members)} 人)\n"
    embed.add_field(name="🛡️ 固定身分組", value=role_text or "無", inline=False)

    # 動態管理員
    if gid in GUILD_MANAGERS and GUILD_MANAGERS[gid]:
        dynamic_text = ""
        for mgr_id in GUILD_MANAGERS[gid]:
            member = guild.get_member(mgr_id)
            if member:
                dynamic_text += f"• {member.mention} (`{mgr_id}`)\n"
            else:
                dynamic_text += f"• `{mgr_id}` (已離開伺服器)\n"
        embed.add_field(name="📋 動態管理員（由超級管理員添加）", value=dynamic_text, inline=False)
    else:
        embed.add_field(name="📋 動態管理員（由超級管理員添加）", value="無", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# 管理命令：商品管理
# ============================================================

@bot.tree.command(name="add-product", description="新增商品到目錄 | Add a product to catalog")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    name="商品名稱",
    emoji="商品 Emoji（如 🔷）",
    description="價格描述（如 1500 tokens/永久）",
    details="商品詳細說明",
    stock="庫存數量（不填則不限庫存）"
)
async def add_product(interaction: discord.Interaction, name: str, emoji: str, description: str, details: str, stock: int = None):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    prices = {}
    for item in description.split("|"):
        item = item.strip()
        if "/" in item:
            parts = item.split("/")
            price = parts[0].strip()
            period = parts[1].strip()
            prices[period] = price
        else:
            prices["預設"] = item

    new_product = {
        "name": name,
        "emoji": "",
        "display_emoji": emoji,
        "description": description,
        "prices": prices,
        "details": details,
        "stock": stock
    }
    PRODUCTS.append(new_product)
    save_products()

    stock_text = f"\n📦 **庫存:** {stock}" if stock is not None else "\n📦 **庫存:** 不限"

    embed = discord.Embed(
        title="✅ 商品已新增",
        description=f"**{emoji} {name}**\n{description}\n\n{details}{stock_text}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="remove-product", description="移除商品 | Remove a product from catalog")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(name="要移除的商品名稱")
async def remove_product(interaction: discord.Interaction, name: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    global PRODUCTS
    original_len = len(PRODUCTS)
    PRODUCTS = [p for p in PRODUCTS if p["name"].lower() != name.lower()]

    if len(PRODUCTS) < original_len:
        save_products()
        await interaction.response.send_message(f"✅ 已移除商品: **{name}**", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ 找不到商品: **{name}**", ephemeral=True)


@bot.tree.command(name="list-products", description="列出所有商品 | List all products")
@app_commands.default_permissions(administrator=True)
async def list_products(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    if not PRODUCTS:
        await interaction.response.send_message("📦 目前沒有商品。", ephemeral=True)
        return

    embed = discord.Embed(title="📦 商品列表 | Product List", color=discord.Color.blue())
    for i, product in enumerate(PRODUCTS, 1):
        stock_val = product.get("stock")
        stock_text = f"\n📦 庫存: {stock_val}" if stock_val is not None else "\n📦 庫存: 不限"
        embed.add_field(
            name=f"{product['display_emoji']} {product['name']}",
            value=f"{product['description']}\n{product['details']}{stock_text}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="set-stock", description="設定商品庫存 | Set product stock")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(name="商品名稱", stock="庫存數量（-1 表示不限庫存）")
async def set_stock(interaction: discord.Interaction, name: str, stock: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    product = next((p for p in PRODUCTS if p["name"].lower() == name.lower()), None)
    if not product:
        await interaction.response.send_message(f"❌ 找不到商品: **{name}**", ephemeral=True)
        return

    if stock < 0:
        product["stock"] = None
        save_products()
        await interaction.response.send_message(f"✅ **{name}** 庫存已設為不限。", ephemeral=True)
    else:
        product["stock"] = stock
        save_products()
        await interaction.response.send_message(f"✅ **{name}** 庫存已設為 **{stock}**。", ephemeral=True)


@bot.tree.command(name="set-price", description="設定當前工單金額（僅管理員）| Set ticket price")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(price="訂單金額（如 1500 tokens）")
async def set_price_cmd(interaction: discord.Interaction, price: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    channel = interaction.channel
    if not channel.topic or ("工單" not in channel.topic and "意見單" not in channel.topic):
        await interaction.response.send_message("❌ 請在工單頻道中使用此命令。", ephemeral=True)
        return

    data = get_ticket_data(channel.id)
    data["price"] = price

    price_embed = discord.Embed(
        title="💰 訂單金額已設定 | Price Set",
        description=(
            f"**金額: {price}**\n\n"
            f"設定者: {interaction.user.mention}\n"
            f"時間: <t:{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}:F>"
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=price_embed)


# ============================================================
# 管理員命令：重啟 / 同步 / 重整
# ============================================================

@bot.tree.command(name="restart", description="🔄 重啟機器人（僅管理員）")
@app_commands.default_permissions(administrator=True)
async def restart_bot(interaction: discord.Interaction):
    """重啟機器人進程"""
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    await interaction.response.send_message(
        "🔄 **機器人正在重啟中...**\n"
        "Railway 將自動重新啟動機器人進程，請稍候約 10-30 秒。",
        ephemeral=True
    )
    await asyncio.sleep(2)
    sys.exit(0)


@bot.tree.command(name="sync", description="🔄 同步斜線命令（僅管理員）")
@app_commands.default_permissions(administrator=True)
async def sync_commands(interaction: discord.Interaction):
    """重新同步所有斜線命令"""
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync(guild=interaction.guild)
        global_synced = await bot.tree.sync()
        await interaction.followup.send(
            f"✅ **斜線命令同步完成！**\n"
            f"• 伺服器命令: {len(synced)} 個\n"
            f"• 全域命令: {len(global_synced)} 個\n"
            f"新命令現在應該已經可以使用了。",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ 同步失敗: {e}", ephemeral=True)


@bot.tree.command(name="refresh", description="🔄 重整機器人狀態（僅管理員）")
@app_commands.default_permissions(administrator=True)
async def refresh_bot(interaction: discord.Interaction):
    """重新載入持久化 View 和同步命令"""
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 僅管理員可使用此命令。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        # 重新載入資料
        load_products()
        load_managers()
        load_guild_config()

        # 重新註冊持久化 View
        bot.add_view(ProductSelectView())
        bot.add_view(InquiryTicketView())
        bot.add_view(CloseTicketView())
        bot.add_view(ConfirmCloseView())
        bot.add_view(ClaimTicketView())
        bot.add_view(AdminTicketView())
        bot.add_view(InquiryAdminView())

        # 同步命令
        synced = await bot.tree.sync(guild=interaction.guild)
        global_synced = await bot.tree.sync()

        await interaction.followup.send(
            f"✅ **機器人狀態已重整！**\n"
            f"• 持久化 View 已重新載入\n"
            f"• 商品資料已重新載入（{len(PRODUCTS)} 個商品）\n"
            f"• 管理員資料已重新載入\n"
            f"• 伺服器配置已重新載入\n"
            f"• 伺服器命令: {len(synced)} 個已同步\n"
            f"• 全域命令: {len(global_synced)} 個已同步\n"
            f"所有功能現在應該已經正常運作。",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ 重整失敗: {e}", ephemeral=True)


# ============================================================
# 啟動 Bot
# ============================================================

if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ 請設置 DISCORD_TOKEN 環境變數！")
        print("在 .env 文件中設置: DISCORD_TOKEN=your_token_here")
        print("或設置環境變數: export DISCORD_TOKEN=your_token_here")
    else:
        bot.run(TOKEN)
