import hashlib
import html
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import List, Literal
from urllib.parse import quote_plus

import streamlit as st
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel


# =========================================================
# APP SETUP
# =========================================================

APP_NAME = "RecycleAgent AI"
MODEL_NAME = "gemini-3.5-flash-lite"
DB_PATH = Path(__file__).with_name("makelift_chats.db")

st.set_page_config(
    page_title=APP_NAME,
    page_icon="♻️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                mode TEXT NOT NULL,
                materials_json TEXT NOT NULL,
                reuse_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
            """
        )

        conn.commit()


def get_setting(key, default):
    with db() as conn:
        row = conn.execute(
            """
            SELECT setting_value
            FROM settings
            WHERE setting_key = ?
            """,
            (key,),
        ).fetchone()

    return row[0] if row else default


def save_setting(key, value):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings (
                setting_key,
                setting_value
            )
            VALUES (?, ?)

            ON CONFLICT(setting_key)
            DO UPDATE SET
                setting_value = excluded.setting_value
            """,
            (
                key,
                str(value),
            ),
        )

        conn.commit()


def create_chat(
    mode,
    materials,
    result,
    question,
):
    title = " ".join(
        question.strip().split()
    )

    if not title:
        title = f"{APP_NAME} Chat"

    if len(title) > 45:
        title = (
            title[:42].rstrip()
            + "..."
        )

    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO conversations (
                title,
                mode,
                materials_json,
                reuse_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                title,
                mode,
                json.dumps(
                    materials,
                    ensure_ascii=False,
                ),
                json.dumps(
                    result,
                    ensure_ascii=False,
                ),
            ),
        )

        conn.commit()

        return cursor.lastrowid


def save_message(
    chat_id,
    role,
    content,
):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO messages (
                conversation_id,
                role,
                content
            )
            VALUES (?, ?, ?)
            """,
            (
                chat_id,
                role,
                content,
            ),
        )

        conn.execute(
            """
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (chat_id,),
        )

        conn.commit()


def list_chats(limit=10):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                title,
                mode
            FROM conversations
            ORDER BY
                updated_at DESC,
                id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return rows


def load_chat(chat_id):
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                title,
                mode,
                materials_json,
                reuse_json
            FROM conversations
            WHERE id = ?
            """,
            (chat_id,),
        ).fetchone()

        messages = conn.execute(
            """
            SELECT
                role,
                content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (chat_id,),
        ).fetchall()

    if not row:
        return None

    return {
        "id": row[0],
        "title": row[1],
        "mode": row[2],
        "materials": json.loads(
            row[3]
        ),
        "result": json.loads(
            row[4]
        ),
        "messages": [
            {
                "role": role,
                "content": content,
            }
            for role, content in messages
        ],
    }


def delete_chat(chat_id):
    with db() as conn:
        conn.execute(
            """
            DELETE FROM messages
            WHERE conversation_id = ?
            """,
            (chat_id,),
        )

        conn.execute(
            """
            DELETE FROM conversations
            WHERE id = ?
            """,
            (chat_id,),
        )

        conn.commit()


init_db()


# =========================================================
# THEMES
# =========================================================

COLOR_THEMES = {

    "🔴 Pastel Red": (
        "#E88787",
        "#F2A3A3",
        "#FCECEC",
        "#3B2528",
        "#FFFFFF",
        "#251416",
    ),

    "🟠 Pastel Orange": (
        "#EFA16F",
        "#F5B58B",
        "#FFF0E6",
        "#3D2B21",
        "#FFFFFF",
        "#28180F",
    ),

    "🟡 Pastel Yellow": (
        "#D8B94E",
        "#F0D777",
        "#FFF8D9",
        "#39331F",
        "#302900",
        "#302900",
    ),

    "🟢 Pastel Green": (
        "#79B98A",
        "#97D5A6",
        "#E9F6EC",
        "#22372A",
        "#FFFFFF",
        "#132219",
    ),

    "🔵 Pastel Blue": (
        "#78A9DE",
        "#9BC3EE",
        "#EAF3FC",
        "#223143",
        "#FFFFFF",
        "#122033",
    ),

    "🟣 Pastel Purple": (
        "#A68AD5",
        "#C0A7EA",
        "#F1EBFA",
        "#302740",
        "#FFFFFF",
        "#21162F",
    ),

    "🩷 Pastel Pink": (
        "#E58DB8",
        "#F0ADD0",
        "#FCEAF3",
        "#3B2632",
        "#FFFFFF",
        "#28141F",
    ),

    "⚫ Black": (
        "#343A40",
        "#F1F3F5",
        "#E9ECEF",
        "#252A30",
        "#FFFFFF",
        "#101214",
    ),
}


saved_color = get_setting(
    "appearance_color",
    "🟢 Pastel Green",
)

if saved_color not in COLOR_THEMES:
    saved_color = "🟢 Pastel Green"


saved_dark = (
    get_setting(
        "appearance_dark",
        "false",
    ).lower()
    == "true"
)


tutorial_seen = (
    get_setting(
        "tutorial_seen",
        "false",
    ).lower()
    == "true"
)


# =========================================================
# SESSION STATE
# =========================================================

DEFAULTS = {

    "entered_app":
        False,

    "play_enter_transition":
        False,

    "appearance_color":
        saved_color,

    "appearance_dark":
        saved_dark,

    "show_tutorial":
        not tutorial_seen,

    "app_mode":
        "📷 Scan Materials",

    "photo_method":
        "Upload an image",

    "scan_result":
        None,

    "scan_reuse":
        None,

    "scan_disposal":
        None,

    "scan_hash":
        "",

    "scan_image_bytes":
        None,

    "scan_image_name":
        "",

    "scan_image_mime":
        "image/jpeg",

    "scan_upload_version":
        0,

    "manual_selected":
        [],

    "manual_custom":
        "",

    "manual_result":
        None,

    "manual_disposal":
        None,

    "manual_safe_materials":
        [],

    "manual_kind":
        "inventory",

    "manual_signature":
        "",

    "school_selected":
        [],

    "school_custom":
        "",

    "school_plan":
        None,

    "school_disposal":
        None,

    "school_signature":
        "",

    "school_class_size":
        20,

    "scan_chat":
        [],

    "scan_chat_id":
        None,

    "manual_chat":
        [],

    "manual_chat_id":
        None,

    "history_chat_id":
        None,

    "recycle_location":
        "",

    "animation_items":
        [],

    "animation_active":
        False,

    "demo_active":
        False,
}


for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[
            key
        ] = value


# =========================================================
# APPEARANCE HELPERS
# =========================================================

def set_theme(name):

    st.session_state[
        "appearance_color"
    ] = name

    save_setting(
        "appearance_color",
        name,
    )

    save_setting(
        "appearance_dark",
        (
            "true"
            if st.session_state[
                "appearance_dark"
            ]
            else
            "false"
        ),
    )


def set_dark(value):

    value = bool(
        value
    )

    st.session_state[
        "appearance_dark"
    ] = value

    save_setting(
        "appearance_color",
        st.session_state[
            "appearance_color"
        ],
    )

    save_setting(
        "appearance_dark",
        (
            "true"
            if value
            else
            "false"
        ),
    )


selected_color = (
    st.session_state[
        "appearance_color"
    ]
)

dark_mode = bool(
    st.session_state[
        "appearance_dark"
    ]
)


(
    light_accent,
    dark_accent,
    light_soft,
    dark_soft,
    light_button_text,
    dark_button_text,
) = COLOR_THEMES[
    selected_color
]


if dark_mode:

    accent = dark_accent
    soft = dark_soft
    button_text = dark_button_text

    if selected_color == "⚫ Black":

        background = "#050607"
        surface = "#15181C"
        surface_2 = "#252A30"
        text = "#FFFFFF"
        muted = "#D7DCE1"
        border = "#69737D"
        sidebar_background = "#0B0D0F"

    else:

        background = "#0D1014"
        surface = "#181C21"
        surface_2 = "#242A31"
        text = "#F8F9FA"
        muted = "#CCD2D8"
        border = "#48515B"
        sidebar_background = "#12161A"

else:

    accent = light_accent
    soft = light_soft
    button_text = light_button_text

    background = "#F8FAFB"
    surface = "#FFFFFF"
    surface_2 = light_soft
    text = "#20252A"
    muted = "#66717A"
    border = "#C8D0D7"
    sidebar_background = "#FFFFFF"


# Black arrows in Light Mode.
arrow_color = (
    "#F8F9FA"
    if dark_mode
    else
    "#000000"
)


# =========================================================
# GLOBAL CSS
# =========================================================

st.html(
    f"""
    <style>

    :root,
    html,
    body,
    .stApp {{

        --ra-accent:
            {accent};

        --ra-soft:
            {soft};

        --ra-bg:
            {background};

        --ra-surface:
            {surface};

        --ra-surface-2:
            {surface_2};

        --ra-text:
            {text};

        --ra-muted:
            {muted};

        --ra-border:
            {border};

        --ra-button-text:
            {button_text};

        --st-primary-color:
            {accent};

        --st-background-color:
            {background};

        --st-secondary-background-color:
            {surface_2};

        --st-text-color:
            {text};

        --st-border-color:
            {border};

        color-scheme:
            {
                "dark"
                if dark_mode
                else
                "light"
            };
    }}


    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {{

        background:
            var(--ra-bg) !important;

        color:
            var(--ra-text) !important;
    }}


    [data-testid="stHeader"] {{

        background:
            transparent !important;
    }}


    [data-testid="stMainBlockContainer"] {{

        padding-top:
            1.25rem;

        padding-bottom:
            5rem;
    }}


    /* =====================================================
       SIDEBAR
    ===================================================== */

    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div {{

        background:
            {sidebar_background} !important;

        color:
            var(--ra-text) !important;
    }}


    [data-testid="stSidebar"] {{

        border-right:
            1px solid
            var(--ra-border) !important;
    }}


    /* =====================================================
       STREAMLIT 1.61.1 SIDEBAR ARROWS
    ===================================================== */

    [data-testid="stSidebarCollapseButton"],
    [data-testid="stExpandSidebarButton"] {{

        visibility:
            visible !important;

        opacity:
            1 !important;

        color:
            {arrow_color} !important;

        -webkit-text-fill-color:
            {arrow_color} !important;

        z-index:
            10000 !important;
    }}


    [data-testid="stSidebarCollapseButton"] *,
    [data-testid="stExpandSidebarButton"] * {{

        color:
            {arrow_color} !important;

        -webkit-text-fill-color:
            {arrow_color} !important;

        fill:
            {arrow_color} !important;

        stroke:
            {arrow_color} !important;

        opacity:
            1 !important;
    }}


    /* =====================================================
       TEXT
    ===================================================== */

    h1,
    h2,
    h3,
    h4,
    h5,
    h6,

    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stWidgetLabel"] p {{

        color:
            var(--ra-text) !important;
    }}


    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p {{

        color:
            var(--ra-muted) !important;
    }}


    /* =====================================================
       BUTTONS
    ===================================================== */

    .stButton > button,
    .stFormSubmitButton > button {{

        background:
            var(--ra-surface) !important;

        color:
            var(--ra-text) !important;

        border:
            1px solid
            var(--ra-border) !important;

        border-radius:
            14px !important;

        min-height:
            2.75rem;

        font-weight:
            650 !important;

        box-shadow:
            none !important;
    }}


    .stButton > button:hover,
    .stFormSubmitButton > button:hover {{

        background:
            var(--ra-surface-2) !important;

        border-color:
            var(--ra-accent) !important;
    }}


    .stButton > button[kind="primary"],
    .stFormSubmitButton > button[kind="primary"],
    [data-testid="stBaseButton-primary"] {{

        background:
            var(--ra-accent) !important;

        color:
            var(--ra-button-text) !important;

        border-color:
            var(--ra-accent) !important;
    }}


    .stButton > button[kind="primary"] *,
    .stFormSubmitButton > button[kind="primary"] *,
    [data-testid="stBaseButton-primary"] * {{

        color:
            var(--ra-button-text) !important;
    }}


    .stLinkButton > a {{

        background:
            var(--ra-accent) !important;

        color:
            var(--ra-button-text) !important;

        border:
            1px solid
            var(--ra-accent) !important;

        border-radius:
            14px !important;

        font-weight:
            650 !important;
    }}


    .stLinkButton > a * {{

        color:
            var(--ra-button-text) !important;
    }}


    /* =====================================================
       TEXT INPUTS
    ===================================================== */

    [data-testid="stTextInput"]
    [data-baseweb="input"],

    [data-testid="stTextInput"]
    [data-baseweb="base-input"],

    [data-testid="stTextInput"]
    input {{

        background:
            var(--ra-surface) !important;

        color:
            var(--ra-text) !important;

        caret-color:
            var(--ra-accent) !important;
    }}


    [data-testid="stTextInput"]
    [data-baseweb="input"] {{

        border:
            1px solid
            var(--ra-border) !important;

        border-radius:
            14px !important;
    }}


    [data-testid="stTextInput"]
    input::placeholder {{

        color:
            var(--ra-muted) !important;
    }}


    /* =====================================================
       FILE UPLOADER
    ===================================================== */

    [data-testid="stFileUploaderDropzone"] {{

        background:
            var(--ra-surface-2) !important;

        color:
            var(--ra-text) !important;

        border:
            1px dashed
            var(--ra-border) !important;

        border-radius:
            18px !important;
    }}


    [data-testid="stFileUploaderDropzone"] * {{

        color:
            var(--ra-text) !important;
    }}


    [data-testid="stFileUploader"] button,
    [data-testid="stCameraInput"] button {{

        background:
            var(--ra-accent) !important;

        color:
            var(--ra-button-text) !important;

        border-color:
            var(--ra-accent) !important;
    }}


    /*
    Hide Streamlit's native selected-file chip.
    After the image is stored the entire uploader
    disappears anyway.
    */

    [data-testid="stFileUploader"]
    [data-testid="stFileChips"],

    [data-testid="stFileUploaderFile"],

    [data-testid="stFileUploaderFileData"],

    [data-testid="stFileUploaderFileName"] {{

        display:
            none !important;
    }}


    /* =====================================================
       EXPANDERS
    ===================================================== */

    [data-testid="stExpander"]
    details {{

        background:
            var(--ra-surface) !important;

        border:
            1px solid
            var(--ra-border) !important;

        border-radius:
            16px !important;

        overflow:
            hidden !important;
    }}


    [data-testid="stExpander"]
    summary {{

        background:
            var(--ra-surface) !important;

        color:
            var(--ra-text) !important;
    }}


    [data-testid="stExpander"]
    summary:hover {{

        background:
            var(--ra-surface-2) !important;
    }}


    [data-testid="stExpander"]
    summary svg,

    [data-testid="stExpander"]
    summary svg *,

    [data-testid="stExpander"]
    summary
    [data-testid="stIconMaterial"],

    [data-testid="stExpander"]
    summary
    [data-testid="stExpanderToggleIcon"] {{

        color:
            {arrow_color} !important;

        fill:
            {arrow_color} !important;

        stroke:
            {arrow_color} !important;

        opacity:
            1 !important;
    }}


    /* =====================================================
       CONTAINERS
    ===================================================== */

    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stChatMessage"] {{

        background:
            var(--ra-surface) !important;

        color:
            var(--ra-text) !important;

        border-color:
            var(--ra-border) !important;

        border-radius:
            18px !important;
    }}


    [data-testid="stMetric"] {{

        background:
            var(--ra-surface-2) !important;

        border:
            1px solid
            var(--ra-border) !important;

        border-radius:
            15px !important;

        padding:
            12px !important;
    }}


    [data-testid="stMetric"] * {{

        color:
            var(--ra-text) !important;
    }}


    /* =====================================================
       LOGO
    ===================================================== */

    .ra-logo {{

        position:
            relative;

        display:
            inline-block;

        width:
            108px;

        height:
            100px;

        flex-shrink:
            0;
    }}


    .ra-recycle {{

        position:
            absolute;

        left:
            50%;

        top:
            0;

        transform:
            translateX(-50%);

        font-size:
            5.1rem;

        line-height:
            1;
    }}


    .ra-plant {{

        position:
            absolute;

        left:
            50%;

        bottom:
            0;

        transform:
            translateX(-50%);

        font-size:
            2.8rem;

        line-height:
            1;

        z-index:
            2;
    }}


    /* =====================================================
       HEADER
    ===================================================== */

    .hero {{

        display:
            flex;

        align-items:
            center;

        gap:
            1.25rem;

        padding:
            0.7rem 0 1.1rem;
    }}


    .hero-title {{

        font-size:
            2.75rem;

        font-weight:
            850;

        line-height:
            1;

        color:
            var(--ra-text);
    }}


    .hero-tag {{

        font-size:
            1.08rem;

        font-weight:
            680;

        color:
            var(--ra-text);

        margin-top:
            0.42rem;
    }}


    .hero-desc {{

        color:
            var(--ra-muted);

        margin-top:
            0.25rem;
    }}


    /* =====================================================
       SIDEBAR BRAND
    ===================================================== */

    .sidebar-brand {{

        text-align:
            center;

        padding-top:
            0.2rem;
    }}


    .sidebar-brand
    .ra-logo {{

        width:
            74px;

        height:
            68px;
    }}


    .sidebar-brand
    .ra-recycle {{

        font-size:
            3.45rem;
    }}


    .sidebar-brand
    .ra-plant {{

        font-size:
            1.9rem;
    }}


    .sidebar-title {{

        font-size:
            1.35rem;

        font-weight:
            820;

        color:
            var(--ra-text);
    }}


    .sidebar-tag {{

        font-size:
            0.75rem;

        color:
            var(--ra-muted);

        margin-top:
            0.28rem;
    }}


    /* =====================================================
       JOURNEY
    ===================================================== */

    .journey {{

        display:
            grid;

        grid-template-columns:
            1fr auto 1fr auto 1fr;

        gap:
            0.45rem;

        align-items:
            center;

        padding:
            0.72rem;

        border:
            1px solid
            var(--ra-border);

        border-radius:
            17px;

        background:
            var(--ra-surface);

        margin:
            0.35rem 0 0.9rem;
    }}


    .journey-step {{

        padding:
            0.58rem;

        text-align:
            center;

        border-radius:
            12px;

        font-weight:
            740;

        color:
            var(--ra-muted);
    }}


    .journey-step.active {{

        background:
            var(--ra-soft);

        border:
            1px solid
            var(--ra-accent);

        color:
            var(--ra-text);
    }}


    .journey-arrow {{

        color:
            var(--ra-muted);

        font-weight:
            900;
    }}


    /* =====================================================
       CARDS
    ===================================================== */

    .purpose {{

        padding:
            0.8rem 0.95rem;

        margin:
            0 0 1rem;

        border-left:
            4px solid
            var(--ra-accent);

        border-radius:
            12px;

        background:
            var(--ra-surface-2);

        color:
            var(--ra-text);
    }}


    .banner {{

        padding:
            0.8rem 0.95rem;

        border-radius:
            15px;

        border:
            1px solid
            var(--ra-border);

        margin:
            0.55rem 0 0.85rem;

        background:
            var(--ra-surface);
    }}


    .banner.reuse {{

        border-left:
            5px solid
            #4F8D5F;
    }}


    .banner.disposal {{

        border-left:
            5px solid
            #C68A28;
    }}


    .banner.unsafe {{

        border-left:
            5px solid
            #C95D5D;
    }}


    .badges {{

        display:
            flex;

        flex-wrap:
            wrap;

        gap:
            0.4rem;

        margin:
            0.4rem 0 0.75rem;
    }}


    .badge {{

        display:
            inline-flex;

        padding:
            0.3rem 0.6rem;

        border-radius:
            999px;

        border:
            1px solid
            var(--ra-accent);

        background:
            var(--ra-soft);

        color:
            var(--ra-text);

        font-size:
            0.8rem;

        font-weight:
            760;
    }}


    .why {{

        padding:
            0.72rem 0.85rem;

        border-radius:
            13px;

        background:
            var(--ra-soft);

        border:
            1px solid
            var(--ra-accent);

        margin:
            0.55rem 0;
    }}


    .material-summary {{

        padding:
            0.7rem 0.85rem;

        margin-top:
            0.55rem;

        border-radius:
            13px;

        background:
            var(--ra-soft);

        border:
            1px solid
            var(--ra-border);
    }}


    .quantity {{

        display:
            flex;

        align-items:
            center;

        justify-content:
            center;

        height:
            2.75rem;

        border-radius:
            13px;

        background:
            var(--ra-surface-2);

        border:
            1px solid
            var(--ra-border);

        font-size:
            1.04rem;

        font-weight:
            800;
    }}


    /* =====================================================
       CUSTOM IMAGE CARD
    ===================================================== */

    .file-card {{

        display:
            flex;

        justify-content:
            space-between;

        align-items:
            center;

        gap:
            0.7rem;

        padding:
            0.8rem 0.9rem;

        margin:
            0.55rem 0 0.9rem;

        border:
            1px solid
            var(--ra-border);

        border-radius:
            14px;

        background:
            var(--ra-surface);

        color:
            var(--ra-text);
    }}


    .file-meta {{

        display:
            flex;

        flex-direction:
            column;

        gap:
            0.12rem;

        min-width:
            0;
    }}


    .file-name {{

        font-weight:
            760;

        color:
            var(--ra-text);

        overflow-wrap:
            anywhere;
    }}


    .file-size {{

        font-size:
            0.84rem;

        color:
            var(--ra-muted);
    }}


    .file-ready {{

        display:
            inline-flex;

        align-items:
            center;

        padding:
            0.3rem 0.6rem;

        border-radius:
            999px;

        background:
            var(--ra-soft);

        border:
            1px solid
            var(--ra-accent);

        color:
            var(--ra-text);

        font-size:
            0.82rem;

        font-weight:
            760;

        white-space:
            nowrap;
    }}


    /* =====================================================
       MATERIAL ANIMATION
    ===================================================== */

    .flight-layer {{

        position:
            fixed;

        inset:
            0;

        z-index:
            1;

        overflow:
            hidden;

        pointer-events:
            none;
    }}


    [data-testid="stMainBlockContainer"],
    [data-testid="stSidebar"] {{

        position:
            relative;

        z-index:
            2;
    }}


    .fly {{

        position:
            absolute;

        right:
            -32vw;

        opacity:
            0;

        white-space:
            nowrap;

        padding:
            0.4rem 0.7rem;

        border-radius:
            999px;

        background:
            var(--ra-surface);

        border:
            1px solid
            var(--ra-accent);

        color:
            var(--ra-text);

        font-weight:
            730;

        animation:
            drift linear forwards;
    }}


    @keyframes drift {{

        0% {{

            transform:
                translateX(0)
                rotate(-5deg);

            opacity:
                0;
        }}


        8% {{

            opacity:
                0.16;
        }}


        50% {{

            transform:
                translateX(-75vw)
                rotate(5deg);

            opacity:
                0.16;
        }}


        100% {{

            transform:
                translateX(-150vw)
                rotate(-7deg);

            opacity:
                0;
        }}
    }}


    /* =====================================================
       MOBILE
    ===================================================== */

    @media (
        max-width:
            700px
    ) {{

        [data-testid="stMainBlockContainer"] {{

            padding-left:
                0.8rem !important;

            padding-right:
                0.8rem !important;

            padding-top:
                0.7rem !important;
        }}


        .hero {{

            flex-direction:
                column;

            text-align:
                center;

            gap:
                0.45rem;
        }}


        .hero-title {{

            font-size:
                2rem;
        }}


        .hero-tag {{

            font-size:
                0.98rem;
        }}


        .journey {{

            grid-template-columns:
                1fr;
        }}


        .journey-arrow {{

            transform:
                rotate(90deg);
        }}


        .file-card {{

            flex-direction:
                column;

            align-items:
                flex-start;
        }}


        .fly:nth-child(n+7) {{

            display:
                none;
        }}
    }}

    </style>
    """
)


# =========================================================
# INTRO SCREEN
# =========================================================

if not st.session_state[
    "entered_app"
]:

    st.html(
        """
        <style>

        [data-testid="stSidebar"],
        [data-testid="stHeader"],
        header {

            display:
                none !important;
        }


        [data-testid="stMainBlockContainer"] {

            max-width:
                none !important;

            padding:
                0 !important;

            margin:
                0 !important;
        }


        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {

            overflow:
                hidden !important;
        }


        .launch {

            position:
                fixed;

            inset:
                0;

            width:
                100vw;

            height:
                100vh;

            z-index:
                999;

            overflow:
                hidden;

            display:
                flex;

            align-items:
                center;

            justify-content:
                center;

            text-align:
                center;

            box-sizing:
                border-box;

            padding:
                0 1rem 100px;

            background:
                linear-gradient(
                    145deg,
                    var(--ra-bg),
                    var(--ra-surface) 48%,
                    var(--ra-soft) 118%
                );

            color:
                var(--ra-text);
        }


        .launch::before {

            content:
                "";

            position:
                absolute;

            inset:
                0;

            opacity:
                0.35;

            background-image:
                radial-gradient(
                    circle,
                    rgba(
                        120,
                        120,
                        120,
                        0.10
                    )
                    0.8px,
                    transparent
                    0.9px
                );

            background-size:
                12px 12px;
        }


        .launch-glow {

            position:
                absolute;

            width:
                560px;

            height:
                560px;

            left:
                50%;

            top:
                43%;

            transform:
                translate(
                    -50%,
                    -50%
                );

            border-radius:
                50%;

            background:
                var(--ra-accent);

            opacity:
                0.12;

            filter:
                blur(
                    125px
                );
        }


        .blob {

            position:
                absolute;

            background:
                var(--ra-accent);

            opacity:
                0.07;

            filter:
                blur(
                    14px
                );

            animation:
                introFloat
                13s
                ease-in-out
                infinite;
        }


        .blob-one {

            width:
                420px;

            height:
                340px;

            left:
                -120px;

            top:
                -90px;

            border-radius:
                42%
                58%
                60%
                40%;
        }


        .blob-two {

            width:
                360px;

            height:
                440px;

            right:
                -120px;

            top:
                13%;

            border-radius:
                62%
                38%
                44%
                56%;

            animation-delay:
                1s;
        }


        .blob-three {

            width:
                480px;

            height:
                270px;

            left:
                18%;

            bottom:
                -150px;

            border-radius:
                54%
                46%
                62%
                38%;

            animation-delay:
                2s;
        }


        .scrap {

            position:
                absolute;

            background:
                var(--ra-surface);

            border:
                1px solid
                var(--ra-border);

            opacity:
                0.30;

            animation:
                scrapFloat
                10s
                ease-in-out
                infinite;
        }


        .scrap-one {

            width:
                120px;

            height:
                78px;

            left:
                8%;

            top:
                27%;

            border-radius:
                20px
                7px
                23px
                9px;
        }


        .scrap-two {

            width:
                95px;

            height:
                125px;

            right:
                9%;

            bottom:
                23%;

            border-radius:
                8px
                24px
                12px
                21px;

            animation-delay:
                1.2s;
        }


        .wave-back {

            position:
                absolute;

            left:
                -12%;

            width:
                124%;

            height:
                24vh;

            bottom:
                -15vh;

            border-radius:
                50%
                50%
                0
                0
                /
                100%
                100%
                0
                0;

            background:
                var(--ra-accent);

            opacity:
                0.10;
        }


        .launch-content {

            position:
                relative;

            z-index:
                5;

            width:
                min(
                    900px,
                    88vw
                );

            transform-origin:
                center;
        }


        .launch-logo {

            position:
                relative;

            width:
                180px;

            height:
                158px;

            margin:
                0 auto
                0.5rem;
        }


        .launch-recycle {

            position:
                absolute;

            left:
                50%;

            top:
                0;

            transform:
                translateX(-50%)
                scale(0.35);

            opacity:
                0;

            font-size:
                8rem;

            line-height:
                1;

            animation:
                recycleAppear
                0.85s
                cubic-bezier(
                    0.34,
                    1.56,
                    0.64,
                    1
                )
                0.28s
                forwards;
        }


        .launch-plant {

            position:
                absolute;

            left:
                50%;

            bottom:
                2px;

            transform:
                translateX(-50%)
                translateY(42px)
                scale(0.15);

            opacity:
                0;

            font-size:
                4.5rem;

            line-height:
                1;

            z-index:
                3;

            animation:
                plantGrow
                0.95s
                cubic-bezier(
                    0.16,
                    1,
                    0.3,
                    1
                )
                0.95s
                forwards;
        }


        .launch-title {

            font-size:
                clamp(
                    3rem,
                    6.5vw,
                    5.5rem
                );

            font-weight:
                900;

            line-height:
                1;

            letter-spacing:
                -0.055em;

            opacity:
                0;

            animation:
                riseIn
                0.7s
                ease-out
                1.48s
                forwards;
        }


        .launch-tag {

            font-size:
                clamp(
                    1rem,
                    2.1vw,
                    1.5rem
                );

            font-weight:
                680;

            margin-top:
                1rem;

            opacity:
                0;

            animation:
                riseIn
                0.65s
                ease-out
                1.85s
                forwards;
        }


        .launch-sub {

            color:
                var(--ra-muted);

            font-size:
                clamp(
                    0.9rem,
                    1.6vw,
                    1.08rem
                );

            margin-top:
                0.5rem;

            opacity:
                0;

            animation:
                riseIn
                0.6s
                ease-out
                2.12s
                forwards;
        }


        .intro-pills {

            display:
                flex;

            justify-content:
                center;

            flex-wrap:
                wrap;

            gap:
                0.7rem;

            margin-top:
                1.3rem;
        }


        .intro-pill {

            padding:
                0.55rem
                1rem;

            border:
                1px solid
                var(--ra-border);

            border-radius:
                999px;

            background:
                var(--ra-surface);

            opacity:
                0;

            animation:
                riseIn
                0.5s
                ease-out
                2.5s
                forwards;
        }


        .credit {

            margin-top:
                1.2rem;

            opacity:
                0;

            animation:
                riseIn
                0.5s
                ease-out
                2.85s
                forwards;
        }


        .created {

            font-size:
                0.72rem;

            letter-spacing:
                0.15em;

            text-transform:
                uppercase;

            color:
                var(--ra-muted);
        }


        .name {

            font-weight:
                760;

            margin-top:
                0.15rem;
        }


        .stButton {

            position:
                fixed !important;

            left:
                50% !important;

            bottom:
                18px !important;

            transform:
                translateX(-50%) !important;

            width:
                min(
                    390px,
                    78vw
                ) !important;

            z-index:
                1001 !important;

            opacity:
                0;

            animation:
                startReveal
                0.6s
                ease-out
                3.1s
                forwards;
        }


        .stButton > button {

            width:
                100% !important;

            min-height:
                3.3rem !important;

            border-radius:
                999px !important;

            background:
                var(--ra-accent) !important;

            color:
                var(--ra-button-text) !important;

            border-color:
                var(--ra-accent) !important;
        }


        @keyframes recycleAppear {

            to {

                opacity:
                    1;

                transform:
                    translateX(-50%)
                    scale(1);
            }
        }


        @keyframes plantGrow {

            to {

                opacity:
                    1;

                transform:
                    translateX(-50%)
                    translateY(0)
                    scale(1);
            }
        }


        @keyframes riseIn {

            from {

                opacity:
                    0;

                transform:
                    translateY(
                        15px
                    );
            }


            to {

                opacity:
                    1;

                transform:
                    translateY(
                        0
                    );
            }
        }


        @keyframes startReveal {

            from {

                opacity:
                    0;

                transform:
                    translateX(-50%)
                    translateY(
                        14px
                    );
            }


            to {

                opacity:
                    1;

                transform:
                    translateX(-50%)
                    translateY(
                        0
                    );
            }
        }


        @keyframes introFloat {

            50% {

                transform:
                    translate(
                        35px,
                        25px
                    )
                    rotate(
                        8deg
                    );
            }
        }


        @keyframes scrapFloat {

            50% {

                transform:
                    translateY(
                        -16px
                    )
                    rotate(
                        9deg
                    );
            }
        }


        @media (
            max-height:
                820px
        ) {

            .launch-content {

                transform:
                    scale(
                        0.86
                    );
            }


            .credit {

                margin-top:
                    0.7rem;
            }


            .intro-pills {

                margin-top:
                    0.8rem;
            }
        }


        @media (
            max-height:
                680px
        ) {

            .launch-content {

                transform:
                    scale(
                        0.72
                    );
            }
        }


        @media (
            max-height:
                590px
        ) {

            .launch-content {

                transform:
                    scale(
                        0.61
                    );
            }
        }


        @media (
            max-width:
                700px
        ) {

            .launch-logo {

                width:
                    135px;

                height:
                    123px;
            }


            .launch-recycle {

                font-size:
                    6rem;
            }


            .launch-plant {

                font-size:
                    3.4rem;
            }


            .launch-title {

                font-size:
                    2.7rem;
            }


            .intro-pill {

                font-size:
                    0.78rem;

                padding:
                    0.48rem
                    0.7rem;
            }


            .launch-content {

                width:
                    92vw;
            }


            .stButton {

                width:
                    84vw !important;
            }
        }

        </style>


        <div class="launch">

            <div class="blob blob-one">
            </div>

            <div class="blob blob-two">
            </div>

            <div class="blob blob-three">
            </div>

            <div class="launch-glow">
            </div>

            <div class="scrap scrap-one">
            </div>

            <div class="scrap scrap-two">
            </div>

            <div class="wave-back">
            </div>


            <div class="launch-content">

                <div class="launch-logo">

                    <div class="launch-recycle">
                        ♻️
                    </div>

                    <div class="launch-plant">
                        🌱
                    </div>

                </div>


                <div class="launch-title">
                    RecycleAgent AI
                </div>


                <div class="launch-tag">
                    Reuse what you can.
                    Recycle what you can’t.
                </div>


                <div class="launch-sub">
                    See waste differently.
                    Discover what it can become.
                </div>


                <div class="intro-pills">

                    <div class="intro-pill">
                        📷 See
                    </div>

                    <div class="intro-pill">
                        💡 Imagine
                    </div>

                    <div class="intro-pill">
                        ♻️ Reuse
                    </div>

                </div>


                <div class="credit">

                    <div class="created">
                        Created by
                    </div>

                    <div class="name">
                        Parinitha Rajan
                    </div>

                </div>

            </div>

        </div>
        """
    )


    if st.button(
        "✨ Start RecycleAgent AI",

        type="primary",

        use_container_width=True,

        key="start_app",
    ):

        st.session_state[
            "entered_app"
        ] = True

        st.session_state[
            "play_enter_transition"
        ] = True

        st.rerun()


    st.stop()


# =========================================================
# INTRO -> APP TRANSITION
# =========================================================

if st.session_state.get(
    "play_enter_transition",
    False,
):

    st.html(
        """
        <style>

        .enter-transition {

            position:
                fixed;

            inset:
                0;

            z-index:
                99999;

            pointer-events:
                none;

            display:
                flex;

            align-items:
                center;

            justify-content:
                center;

            background:
                linear-gradient(
                    145deg,
                    var(--ra-bg),
                    var(--ra-surface),
                    var(--ra-soft)
                );

            animation:
                transitionFade
                0.9s
                forwards;
        }


        .enter-logo {

            font-size:
                7rem;

            animation:
                transitionLift
                0.82s
                forwards;
        }


        @keyframes transitionLift {

            55% {

                transform:
                    translateY(
                        -20px
                    )
                    scale(
                        1.12
                    );
            }


            to {

                transform:
                    translateY(
                        -70px
                    )
                    scale(
                        0.8
                    );

                opacity:
                    0;
            }
        }


        @keyframes transitionFade {

            0%,
            55% {

                opacity:
                    1;
            }


            to {

                opacity:
                    0;
            }
        }

        </style>


        <div class="enter-transition">

            <div class="enter-logo">
                ♻️🌱
            </div>

        </div>
        """
    )


    st.session_state[
        "play_enter_transition"
    ] = False


# =========================================================
# MATERIAL DATA
# =========================================================

MATERIAL_OPTIONS = [

    "Cardboard",
    "Paper",
    "Paper tubes",
    "Cardboard boxes",
    "Plastic bottles",
    "Plastic containers",
    "Bottle caps",
    "String",
    "Fabric",
    "Popsicle sticks",
    "Old folders",
    "Packaging",
    "Egg cartons",
    "Paper bags",
]


MATERIAL_EMOJI = {

    "cardboard":
        "📦",

    "paper":
        "📄",

    "paper tubes":
        "🧻",

    "cardboard boxes":
        "📦",

    "plastic bottles":
        "🧴",

    "plastic containers":
        "🥡",

    "bottle caps":
        "🔵",

    "string":
        "🧵",

    "fabric":
        "🧶",

    "popsicle sticks":
        "🪵",

    "old folders":
        "📁",

    "packaging":
        "📦",

    "egg cartons":
        "🥚",

    "paper bags":
        "🛍️",
}


CAUTION_WORDS = [

    "battery",
    "batteries",
    "needle",
    "syringe",
    "chemical",
    "acid",
    "bleach",
    "medicine",
    "medical waste",
    "broken glass",
    "gasoline",
    "petrol",
    "fuel",
    "explosive",
    "ammunition",
    "aerosol",
    "unknown liquid",
    "razor",
    "pesticide",
    "paint thinner",
    "motor oil",
]


BREAKDOWN = {

    "paper":
        (
            "Often weeks to a few months "
            "in favorable conditions; "
            "landfill conditions can make "
            "breakdown much slower."
        ),

    "cardboard":
        (
            "Often a few months in favorable "
            "conditions; coatings and disposal "
            "conditions can make this much slower."
        ),

    "paper tubes":
        (
            "Usually similar to cardboard "
            "and often takes months in "
            "favorable conditions."
        ),

    "cardboard boxes":
        (
            "Usually similar to cardboard "
            "and often takes months in "
            "favorable conditions."
        ),

    "paper bags":
        (
            "Often weeks to months in "
            "favorable conditions, depending "
            "on coatings."
        ),

    "fabric":
        (
            "Natural fibers may break down "
            "over months to years; synthetic "
            "fabrics can persist much longer."
        ),

    "string":
        (
            "Depends on the fiber. Natural fibers "
            "may break down over months to years, "
            "while synthetic string can persist "
            "much longer."
        ),

    "popsicle sticks":
        (
            "Untreated wood may take months "
            "to several years depending on "
            "moisture and environment."
        ),

    "plastic bottles":
        (
            "Plastic can persist for many "
            "decades or longer and may fragment "
            "instead of quickly biodegrading."
        ),

    "plastic containers":
        (
            "Plastic can persist for many "
            "decades or longer and may fragment "
            "instead of quickly biodegrading."
        ),

    "bottle caps":
        (
            "Plastic caps can persist for many "
            "decades or longer depending on "
            "plastic type and environment."
        ),

    "old folders":
        (
            "Depends on whether the folder "
            "is mainly paper, plastic, or "
            "mixed material."
        ),

    "packaging":
        (
            "Varies widely. Paper-based packaging "
            "generally breaks down faster than "
            "plastic or multilayer packaging."
        ),

    "egg cartons":
        (
            "Paper-pulp cartons may break down "
            "over weeks to months; plastic or "
            "foam versions persist much longer."
        ),
}


# =========================================================
# MATERIAL HELPERS
# =========================================================

def safe_key(text):

    return hashlib.sha1(
        text.encode(
            "utf-8"
        )
    ).hexdigest()[:10]


def parse_custom(text):

    parts = (
        text
        .replace(
            "\n",
            ",",
        )
        .replace(
            ";",
            ",",
        )
        .split(",")
    )

    output = []
    seen = set()


    for part in parts:

        part = (
            part.strip()
        )

        lower = (
            part.lower()
        )

        if (
            part
            and
            lower not in seen
        ):

            seen.add(
                lower
            )

            output.append(
                part
            )


    return output[:20]


def merge_names(
    first,
    second,
):

    output = []
    seen = set()


    for item in (
        first
        +
        second
    ):

        item = (
            item.strip()
        )

        lower = (
            item.lower()
        )

        if (
            item
            and
            lower not in seen
        ):

            seen.add(
                lower
            )

            output.append(
                item
            )


    return output


def emoji_for(name):

    lower = (
        name.lower()
        .strip()
    )


    if lower in MATERIAL_EMOJI:

        return MATERIAL_EMOJI[
            lower
        ]


    for known, emoji in (
        MATERIAL_EMOJI.items()
    ):

        if (
            known in lower
            or
            lower in known
        ):

            return emoji


    return "♻️"


def queue_animation(items):

    cleaned = []
    seen = set()


    for item in items:

        if isinstance(
            item,
            dict,
        ):

            item = item.get(
                "name",
                "",
            )


        item = (
            str(item)
            .strip()
        )

        lower = (
            item.lower()
        )


        if (
            item
            and
            lower not in seen
        ):

            seen.add(
                lower
            )

            cleaned.append(
                item
            )


    if cleaned:

        st.session_state[
            "animation_items"
        ] = cleaned[:6]

        st.session_state[
            "animation_active"
        ] = True


def custom_input_changed(key):

    queue_animation(
        parse_custom(
            st.session_state.get(
                key,
                "",
            )
        )
    )


def render_animation():

    if not st.session_state.get(
        "animation_active",
        False,
    ):

        return


    items = st.session_state.get(
        "animation_items",
        [],
    )


    if not items:

        return


    repeated = (
        items
        *
        3
    )[:12]


    top_positions = [
        9,
        18,
        29,
        41,
        54,
        66,
        77,
        14,
        35,
        59,
        72,
        86,
    ]


    delays = [
        0,
        0.18,
        0.36,
        0.07,
        0.48,
        0.24,
        0.63,
        0.82,
        0.97,
        1.12,
        0.54,
        1.28,
    ]


    durations = [
        5.4,
        5.9,
        6.5,
        5.6,
        6.2,
        5.7,
        6.8,
        5.5,
        6.1,
        6.6,
        5.8,
        6.9,
    ]


    nodes = []


    for index, item in enumerate(
        repeated
    ):

        nodes.append(
            (
                '<div class="fly" '
                f'style="top:{top_positions[index]}%;'
                f'animation-delay:{delays[index]}s;'
                f'animation-duration:{durations[index]}s;">'
                f'{emoji_for(item)} '
                f'{html.escape(item)}'
                '</div>'
            )
        )


    st.html(
        '<div class="flight-layer">'
        +
        "".join(
            nodes
        )
        +
        "</div>"
    )


    st.session_state[
        "animation_active"
    ] = False


def breakdown_text(name):

    lower = (
        name.lower()
        .strip()
    )


    if lower in BREAKDOWN:

        return BREAKDOWN[
            lower
        ]


    for key, value in (
        BREAKDOWN.items()
    ):

        if (
            key in lower
            or
            lower in key
        ):

            return value


    return (
        "Varies widely with composition "
        "and conditions. Treat this only "
        "as general educational context."
    )


def maps_url(
    query,
    location="",
):

    query = (
        query.strip()
        or
        "recycling center"
    )

    location = (
        location.strip()
    )


    if location:

        full_query = (
            f"{query} near {location}"
        )

    else:

        full_query = (
            f"{query} near me"
        )


    return (
        "https://www.google.com/maps/search/"
        "?api=1&query="
        +
        quote_plus(
            full_query
        )
    )


def show_breakdown(names):

    names = [
        name
        for name in names
        if name
    ]


    if not names:

        return


    with st.expander(
        "⏳ Decomposition time (optional)",

        expanded=False,
    ):

        st.caption(
            "These are broad educational ranges. "
            "Actual breakdown depends on material, "
            "coatings, moisture, oxygen, temperature "
            "and disposal conditions."
        )


        for name in names:

            st.write(
                f"**{name}:** "
                +
                breakdown_text(
                    name
                )
            )


def choice_buttons(
    options,
    state_key,
    prefix,
):

    current = (
        st.session_state[
            state_key
        ]
    )


    columns = st.columns(
        len(options)
    )


    for index, option in enumerate(
        options
    ):

        selected = (
            current
            ==
            option
        )


        with columns[index]:

            if st.button(
                (
                    "✓ "
                    if selected
                    else
                    ""
                )
                +
                option,

                key=(
                    f"{prefix}_"
                    f"{index}"
                ),

                type=(
                    "primary"
                    if selected
                    else
                    "secondary"
                ),

                use_container_width=True,
            ):

                if current != option:

                    st.session_state[
                        state_key
                    ] = option

                    st.rerun()


def material_picker(
    prefix,
    title,
):

    selected_key = (
        f"{prefix}_selected"
    )

    custom_key = (
        f"{prefix}_custom"
    )


    st.write(
        f"**{title}**"
    )


    st.caption(
        "Choose common materials "
        "or type your own."
    )


    with st.container(
        border=True
    ):

        st.write(
            "**Choose options**"
        )


        columns = st.columns(
            3
        )


        for index, material in enumerate(
            MATERIAL_OPTIONS
        ):

            selected = (
                material
                in
                st.session_state[
                    selected_key
                ]
            )


            with columns[
                index % 3
            ]:

                if st.button(
                    (
                        "✓ "
                        if selected
                        else
                        ""
                    )
                    +
                    material,

                    key=(
                        f"{prefix}"
                        f"_material_"
                        f"{index}"
                    ),

                    type=(
                        "primary"
                        if selected
                        else
                        "secondary"
                    ),

                    use_container_width=True,
                ):

                    current = list(
                        st.session_state[
                            selected_key
                        ]
                    )


                    if material in current:

                        current.remove(
                            material
                        )

                    else:

                        current.append(
                            material
                        )


                    st.session_state[
                        selected_key
                    ] = current


                    if (
                        prefix
                        ==
                        "manual"
                    ):

                        st.session_state[
                            "demo_active"
                        ] = False


                    queue_animation(
                        current
                        or
                        [
                            material
                        ]
                    )


                    st.rerun()


        st.divider()


        custom = st.text_input(
            "Type other materials",

            placeholder=(
                "Example: old newspaper, "
                "yogurt cups, cereal box"
            ),

            key=custom_key,

            on_change=(
                custom_input_changed
            ),

            args=(
                custom_key,
            ),
        )


    typed = parse_custom(
        custom
    )


    names = merge_names(
        st.session_state[
            selected_key
        ],
        typed,
    )


    if names:

        st.html(
            f"""
            <div class="material-summary">

                <strong>
                    Selected:
                </strong>

                {
                    html.escape(
                        ", ".join(
                            names
                        )
                    )
                }

            </div>
            """
        )


    caution = [
        item
        for item in typed
        if any(
            word in item.lower()
            for word
            in CAUTION_WORDS
        )
    ]


    if caution:

        st.warning(
            "These may need safe-disposal "
            "guidance instead of reuse: "
            +
            ", ".join(
                caution
            )
            +
            ". The AI will assess them before "
            "suggesting a project."
        )


    return (
        names,
        typed,
    )


def stepper(
    label,
    key,
    default,
    minimum,
    maximum,
    large=False,
):

    if key not in st.session_state:

        st.session_state[
            key
        ] = default


    try:

        value = int(
            st.session_state[
                key
            ]
        )

    except Exception:

        value = default


    value = max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


    st.session_state[
        key
    ] = value


    st.write(
        f"**{label}**"
    )


    if large:

        columns = st.columns(
            [
                1,
                1,
                2,
                1,
                1,
            ]
        )

        actions = [
            (
                -5,
                "−5",
            ),
            (
                -1,
                "−",
            ),
            (
                None,
                None,
            ),
            (
                1,
                "+",
            ),
            (
                5,
                "+5",
            ),
        ]

    else:

        columns = st.columns(
            [
                1,
                2,
                1,
            ]
        )

        actions = [
            (
                -1,
                "−",
            ),
            (
                None,
                None,
            ),
            (
                1,
                "+",
            ),
        ]


    for index, (
        delta,
        label_text,
    ) in enumerate(
        actions
    ):

        with columns[index]:

            if delta is None:

                st.html(
                    f"""
                    <div class="quantity">
                        {value}
                    </div>
                    """
                )

            else:

                if st.button(
                    label_text,

                    key=(
                        f"{key}_"
                        f"{index}"
                    ),

                    use_container_width=True,
                ):

                    st.session_state[
                        key
                    ] = max(
                        minimum,
                        min(
                            maximum,
                            value
                            +
                            delta,
                        ),
                    )

                    st.rerun()


    return value


# =========================================================
# AI SCHEMAS
# =========================================================

class Material(
    BaseModel
):

    name: str

    quantity: int

    confidence: Literal[
        "High",
        "Medium",
        "Low",
    ]

    condition: Literal[
        "Reusable",
        "Damaged but reusable",
        "Too damaged to reuse",
        "Unclear",
    ]

    safe_to_handle: bool

    safety_note: str


class ScanResult(
    BaseModel
):

    materials: List[
        Material
    ]

    unsafe_material_detected: bool

    safety_warning: str

    scan_summary: str


class ReuseIdea(
    BaseModel
):

    title: str

    difficulty: Literal[
        "Easy",
        "Medium",
        "Hard",
    ]

    estimated_time: str

    materials_used: List[
        str
    ]

    additional_materials: List[
        str
    ]

    tools_needed: List[
        str
    ]

    description: str

    steps: List[
        str
    ]

    safety_notes: List[
        str
    ]

    environmental_benefit: str

    video_search_query: str

    best_for: List[
        str
    ]

    why_chosen: str


class ReuseResult(
    BaseModel
):

    best_idea: ReuseIdea

    other_ideas: List[
        ReuseIdea
    ]

    materials_reused: int

    new_materials_required: int

    impact_message: str


class AssessmentItem(
    BaseModel
):

    name: str

    safe_for_reuse: bool

    reason: str


class AssessmentResult(
    BaseModel
):

    materials: List[
        AssessmentItem
    ]


class DisposalItem(
    BaseModel
):

    name: str

    reason_not_to_reuse: str

    safer_disposal: str

    do_not_do: List[
        str
    ]

    facility_search_query: str


class DisposalResult(
    BaseModel
):

    items: List[
        DisposalItem
    ]

    general_message: str


class SchoolMaterialUse(
    BaseModel
):

    name: str

    quantity_per_group: int


class SchoolProject(
    BaseModel
):

    title: str

    difficulty: Literal[
        "Easy",
        "Medium",
        "Hard",
    ]

    estimated_time: str

    group_size: int

    groups_supported: int

    materials_per_group: List[
        SchoolMaterialUse
    ]

    additional_materials: List[
        str
    ]

    tools_needed: List[
        str
    ]

    description: str

    steps: List[
        str
    ]

    safety_notes: List[
        str
    ]

    educational_value: str

    environmental_benefit: str

    video_search_query: str

    best_for: List[
        str
    ]

    why_chosen: str


class SchoolPlan(
    BaseModel
):

    project: SchoolProject

    class_message: str


# =========================================================
# GEMINI
# =========================================================

try:

    API_KEY = st.secrets[
        "GEMINI_API_KEY"
    ]


except KeyError:

    st.error(
        "Gemini API key not found. "
        "Check .streamlit/secrets.toml."
    )

    st.stop()


@st.cache_resource
def get_client(key):

    return genai.Client(
        api_key=key
    )


client = get_client(
    API_KEY
)


def structured(
    prompt,
    schema,
    temperature=0.3,
    image=None,
):

    if image is not None:

        contents = [
            prompt,
            image,
        ]

    else:

        contents = prompt


    response = (
        client.models.generate_content(

            model=MODEL_NAME,

            contents=contents,

            config=(
                types.GenerateContentConfig(

                    response_mime_type=(
                        "application/json"
                    ),

                    response_schema=schema,

                    temperature=(
                        temperature
                    ),
                )
            ),
        )
    )


    if not response.text:

        raise ValueError(
            "The AI returned "
            "an empty response."
        )


    return json.loads(
        response.text
    )


def assess_materials(
    materials,
):

    prompt = f"""
You are the safety gate for {APP_NAME}.

Assess these user-entered materials before
they can be used in a reuse project:

{json.dumps(
    materials,
    ensure_ascii=False,
    indent=2,
)}

Mark safe_for_reuse = true only for
ordinary, clean, low-risk materials
a student can reasonably handle.

Mark safe_for_reuse = false for:

- batteries
- chemicals
- medical waste
- broken glass
- sharp hazards
- contaminated waste
- flammable materials
- dangerous electronics
- unknown liquids
- anything uncertain enough that
  reuse should not be encouraged

Give a short reason.

Do not give disposal instructions yet.
"""


    return structured(
        prompt,
        AssessmentResult,
        temperature=0.1,
    )


def generate_disposal(
    materials,
):

    prompt = f"""
You are the safe-disposal assistant
for {APP_NAME}.

These items should not be reused:

{json.dumps(
    materials,
    ensure_ascii=False,
    indent=2,
)}

For each item:

1. Explain briefly why reuse
   is not recommended.

2. Give cautious, general
   safer-disposal guidance.

3. List important things
   NOT to do.

4. Give a short
   facility_search_query
   suitable for a Maps search.

Never tell the user to:

- open
- puncture
- dismantle
- burn
- crush
- drain
- mix
- neutralize
- taste
- closely smell
- manipulate a hazardous item

Never recommend pouring
chemicals or unknown liquids
down a drain.

Local disposal rules can differ.
"""


    return structured(
        prompt,
        DisposalResult,
        temperature=0.15,
    )


def generate_reuse(
    materials,
):

    prompt = f"""
You are the reuse recommendation
system for {APP_NAME}.

CONFIRMED SAFE INVENTORY:

{json.dumps(
    materials,
    ensure_ascii=False,
    indent=2,
)}

Create:

- ONE best useful reuse project
- 2 to 4 different alternatives

RULES:

1. Respect exact quantities.

2. Prioritize materials
   already present.

3. Use few extra materials.

4. Prefer useful,
   realistic student projects.

5. Safety is more important
   than creativity.

Never suggest:

- fire
- weapons
- dangerous chemicals
- broken glass
- batteries
- dangerous electricity
- dangerous heat
- pressure containers
- contaminated waste
- unknown substances

Ordinary extras may include:

- glue
- tape
- markers
- ruler
- safe scissors

Give:

- clear numbered steps
- realistic estimated time
- safety notes
- environmental benefit

video_search_query must only
be a useful YouTube search phrase.

best_for must contain
1 to 3 short labels such as:

- Quick project
- Classroom
- No cutting
- Few extras

why_chosen must explain why
the idea ranks well for
the supplied materials.

materials_reused is an
approximate count of supplied
pieces used by the best project.

new_materials_required counts
TYPES of extra materials.

Never invent exact
environmental statistics.
"""


    return structured(
        prompt,
        ReuseResult,
        temperature=0.35,
    )


def generate_general_reuse():

    prompt = f"""
You are {APP_NAME}.

The user has NOT selected
any materials.

Suggest:

- ONE best reuse possibility
- 2 to 4 alternatives

Use common low-risk discarded
materials often found at home
or school.

Do not claim the user owns
the materials.

In materials_used,
list what they could look for.

Prefer:

- useful projects
- safe projects
- easy projects
- few purchased extras

Never suggest:

- hazardous materials
- fire
- weapons
- broken glass
- batteries
- unsafe electricity
- dangerous heat
- contaminated waste

Give best_for labels
and why_chosen.

video_search_query must only
be a search phrase.

impact_message must describe
a POSSIBILITY, not an
accomplishment.

Never invent exact
environmental statistics.
"""


    return structured(
        prompt,
        ReuseResult,
        temperature=0.45,
    )


def generate_school(
    materials,
    class_size,
):

    prompt = f"""
You are School Mode
for {APP_NAME}.

CLASS SIZE:
{class_size}

SAFE CLASSROOM INVENTORY:

{json.dumps(
    materials,
    ensure_ascii=False,
    indent=2,
)}

Create ONE practical
classroom reuse project.

RULES:

1. Respect exact inventory.

2. Use exact supplied
   material names inside
   materials_per_group.

3. Never require more
   material than exists.

4. Choose a sensible group
   size, usually 2 to 5.

5. Try to involve the
   whole class.

6. Prioritize:

- safety
- usefulness
- education
- few extras
- realistic classroom timing

Never suggest:

- fire
- weapons
- dangerous chemicals
- broken glass
- batteries
- unsafe electricity
- dangerous heat
- hazardous cutting

Include:

- best_for labels
- why_chosen
- safety notes
- educational value
- environmental benefit
- class_message

video_search_query must only
be a useful search phrase.
"""


    return structured(
        prompt,
        SchoolPlan,
        temperature=0.25,
    )


def validate_school_plan(
    materials,
    plan,
):

    available = {

        item[
            "name"
        ].strip().lower():

        int(
            item[
                "quantity"
            ]
        )

        for item in materials
    }


    project = plan.get(
        "project",
        {},
    )


    groups = max(
        1,
        int(
            project.get(
                "groups_supported",
                1,
            )
        ),
    )


    for item in project.get(
        "materials_per_group",
        [],
    ):

        name = (
            item.get(
                "name",
                "",
            )
            .strip()
        )

        lower = (
            name.lower()
        )


        if lower not in available:

            raise ValueError(
                f"The plan tried to use "
                f"'{name}', which is not "
                "in the classroom inventory."
            )


        quantity_per_group = max(
            0,
            int(
                item.get(
                    "quantity_per_group",
                    0,
                )
            ),
        )


        total_needed = (
            quantity_per_group
            *
            groups
        )


        if (
            total_needed
            >
            available[
                lower
            ]
        ):

            raise ValueError(
                f"The plan needs "
                f"{total_needed} {name}, "
                f"but only "
                f"{available[lower]} "
                "are available."
            )


    return plan


def ask_ai(
    materials,
    result,
    messages,
    question,
):

    inventory_note = (
        (
            "The inventory is confirmed. "
            "Respect quantities exactly."
        )
        if materials
        else
        (
            "These are general suggestions. "
            "Do not claim the user owns "
            "the materials."
        )
    )


    prompt = f"""
You are Ask {APP_NAME}.

MATERIALS:

{json.dumps(
    materials,
    ensure_ascii=False,
)}

CURRENT PROJECT DATA:

{json.dumps(
    result,
    ensure_ascii=False,
)}

RECENT CHAT:

{json.dumps(
    messages[-6:],
    ensure_ascii=False,
)}

QUESTION:

{question}

{inventory_note}

Stay focused on the current
reuse project.

You may adapt it for:

- no glue
- no cutting
- easier
- faster
- fewer extras
- classroom use

Do not invent unavailable materials.

Never give dangerous instructions
involving:

- fire
- weapons
- hazardous chemicals
- broken glass
- unsafe electricity
- dangerous heat
- batteries
- contaminated waste
- sharp hazards

Keep the answer concise
and student-friendly.

Never invent exact
environmental statistics.
"""


    response = (
        client.models.generate_content(

            model=MODEL_NAME,

            contents=prompt,
        )
    )


    if not response.text:

        raise ValueError(
            "The AI returned "
            "an empty response."
        )


    return response.text


# =========================================================
# DISPLAY HELPERS
# =========================================================

def banner(
    kind,
    title,
    body,
):

    st.html(
        f"""
        <div class="banner {kind}">

            <strong>
                {html.escape(title)}
            </strong>

            <br>

            {html.escape(body)}

        </div>
        """
    )


def badges(items):

    if not items:

        return


    content = "".join(
        (
            '<span class="badge">'
            +
            html.escape(
                item
            )
            +
            "</span>"
        )
        for item in items[:3]
    )


    st.html(
        '<div class="badges">'
        +
        content
        +
        "</div>"
    )


def journey(
    active="reuse",
):

    labels = [
        (
            "detect",
            "📷 Detect",
        ),
        (
            "reuse",
            "♻️ Reuse",
        ),
        (
            "dispose",
            "⚠️ Dispose Safely",
        ),
    ]


    pieces = []


    for index, (
        key,
        label,
    ) in enumerate(
        labels
    ):

        active_class = (
            "active"
            if key == active
            else
            ""
        )


        pieces.append(
            f"""
            <div class="
                journey-step
                {active_class}
            ">
                {label}
            </div>
            """
        )


        if index < 2:

            pieces.append(
                """
                <div class="journey-arrow">
                    →
                </div>
                """
            )


    st.html(
        '<div class="journey">'
        +
        "".join(
            pieces
        )
        +
        "</div>"
    )


def show_idea_details(
    idea,
):

    with st.expander(
        "📖 Build Guide",
        expanded=False,
    ):

        st.write(
            "**Estimated time:** "
            +
            idea.get(
                "estimated_time",
                "Unknown",
            )
        )


        st.write(
            "**Tools needed**"
        )


        tools = idea.get(
            "tools_needed",
            [],
        )


        if tools:

            for tool in tools:

                st.write(
                    f"• {tool}"
                )

        else:

            st.write(
                "No special tools."
            )


        st.write(
            "**Steps**"
        )


        for number, step in enumerate(
            idea.get(
                "steps",
                [],
            ),
            start=1,
        ):

            st.markdown(
                f"**{number}.** {step}"
            )


        safety_notes = (
            idea.get(
                "safety_notes",
                [],
            )
        )


        if safety_notes:

            st.write(
                "**Safety notes**"
            )


            for note in safety_notes:

                st.warning(
                    note
                )


        search_query = (
            idea.get(
                "video_search_query",
                "",
            )
        )


        if not search_query:

            search_query = (
                idea.get(
                    "title",
                    "reuse project",
                )
                +
                " DIY tutorial"
            )


        youtube_url = (
            "https://www.youtube.com/"
            "results?search_query="
            +
            quote_plus(
                search_query
            )
        )


        st.link_button(
            "▶️ Find Video Tutorial",

            youtube_url,

            use_container_width=True,
        )


        st.caption(
            "This opens YouTube search results. "
            "RecycleAgent AI does not verify "
            "a specific external video."
        )


def show_reuse(
    result,
    prefix,
    inventory_known=True,
):

    if not result:

        return


    best = result.get(
        "best_idea",
        {},
    )


    st.divider()


    banner(
        "reuse",

        "♻️ Reuse route",

        (
            "These materials can still "
            "become something useful."
            if inventory_known
            else
            (
                "Here is a reuse possibility "
                "using common materials you "
                "could look for."
            )
        ),
    )


    st.caption(
        (
            "BEST REUSE IDEA"
            if inventory_known
            else
            "SUGGESTED REUSE IDEA"
        )
    )


    st.header(
        best.get(
            "title",
            "Reuse Project",
        )
    )


    badges(
        best.get(
            "best_for",
            [],
        )
    )


    why_chosen = (
        best.get(
            "why_chosen",
            "",
        )
        .strip()
    )


    if why_chosen:

        st.html(
            f"""
            <div class="why">

                <strong>
                    ✨ Why {APP_NAME} chose this:
                </strong>

                <br>

                {html.escape(why_chosen)}

            </div>
            """
        )


    metric_1, metric_2, metric_3 = (
        st.columns(3)
    )


    with metric_1:

        st.metric(
            "Difficulty",

            best.get(
                "difficulty",
                "Unknown",
            ),
        )


    with metric_2:

        st.metric(
            "Estimated time",

            best.get(
                "estimated_time",
                "Unknown",
            ),
        )


    with metric_3:

        st.metric(
            "Extra material types",

            len(
                best.get(
                    "additional_materials",
                    [],
                )
            ),
        )


    with st.expander(
        "📦 Materials & Description",

        expanded=False,
    ):

        st.write(
            (
                "**Materials used**"
                if inventory_known
                else
                "**Materials to look for**"
            )
        )


        for item in best.get(
            "materials_used",
            [],
        ):

            st.write(
                f"• {item}"
            )


        st.write(
            "**Extra materials**"
        )


        extras = best.get(
            "additional_materials",
            [],
        )


        if extras:

            for item in extras:

                st.write(
                    f"• {item}"
                )

        else:

            st.success(
                "None"
            )


        st.write(
            "**What you'll make**"
        )


        st.write(
            best.get(
                "description",
                "",
            )
        )


        st.write(
            "**Environmental benefit**"
        )


        st.write(
            best.get(
                "environmental_benefit",
                "",
            )
        )


    show_idea_details(
        best
    )


    st.subheader(
        "♻️ Impact Summary"
    )


    impact_1, impact_2, impact_3 = (
        st.columns(3)
    )


    with impact_1:

        st.metric(
            (
                "Materials reused"
                if inventory_known
                else
                "Suggested discarded pieces"
            ),

            result.get(
                "materials_reused",
                0,
            ),
        )


    with impact_2:

        st.metric(
            "New material types needed",

            result.get(
                "new_materials_required",
                0,
            ),
        )


    with impact_3:

        st.metric(
            "Waste kept in use",

            "Longer",
        )


    if result.get(
        "impact_message"
    ):

        st.info(
            result[
                "impact_message"
            ]
        )


    st.subheader(
        "💡 More Reuse Ideas"
    )


    for number, idea in enumerate(
        result.get(
            "other_ideas",
            [],
        ),
        start=1,
    ):

        with st.expander(
            (
                f"{number}. "
                +
                idea.get(
                    "title",
                    "Reuse Idea",
                )
            ),

            expanded=False,
        ):

            badges(
                idea.get(
                    "best_for",
                    [],
                )
            )


            if idea.get(
                "why_chosen"
            ):

                st.write(
                    "**Why it stands out:** "
                    +
                    idea[
                        "why_chosen"
                    ]
                )


            st.write(
                idea.get(
                    "description",
                    "",
                )
            )


            st.write(
                "**Difficulty:** "
                +
                idea.get(
                    "difficulty",
                    "Unknown",
                )
            )


            st.write(
                "**Time:** "
                +
                idea.get(
                    "estimated_time",
                    "Unknown",
                )
            )


            st.write(
                "**Materials:** "
                +
                ", ".join(
                    idea.get(
                        "materials_used",
                        [],
                    )
                )
            )


            st.write(
                "**Steps**"
            )


            for step_number, step in enumerate(
                idea.get(
                    "steps",
                    [],
                ),
                start=1,
            ):

                st.markdown(
                    f"**{step_number}.** "
                    f"{step}"
                )


            search_query = (
                idea.get(
                    "video_search_query",
                    "",
                )
            )


            if search_query:

                st.link_button(
                    "▶️ Search Tutorial",

                    (
                        "https://www.youtube.com/"
                        "results?search_query="
                        +
                        quote_plus(
                            search_query
                        )
                    ),

                    use_container_width=True,
                )


def show_disposal(
    result,
    prefix,
):

    if not result:

        return


    st.divider()


    banner(
        "disposal",

        "⚠️ Safe disposal route",

        result.get(
            "general_message",
            (
                "Some items should "
                "not be reused."
            ),
        ),
    )


    journey(
        "dispose"
    )


    disposal_items = (
        result.get(
            "items",
            [],
        )
    )


    for index, item in enumerate(
        disposal_items,
        start=1,
    ):

        item_name = (
            item.get(
                "name",
                "Item",
            )
        )


        with st.expander(
            (
                "🛡️ "
                +
                item_name
                +
                " — Safe Disposal"
            ),

            expanded=(
                index == 1
            ),
        ):

            st.write(
                "**Why reuse is "
                "not recommended**"
            )


            st.write(
                item.get(
                    "reason_not_to_reuse",
                    "",
                )
            )


            st.write(
                "**Safer disposal approach**"
            )


            st.write(
                item.get(
                    "safer_disposal",
                    "",
                )
            )


            do_not = (
                item.get(
                    "do_not_do",
                    [],
                )
            )


            if do_not:

                st.write(
                    "**Do not**"
                )


                for warning in do_not:

                    st.warning(
                        warning
                    )


            search_query = (
                item.get(
                    "facility_search_query",
                    "",
                )
            )


            if not search_query:

                search_query = (
                    f"{item_name} "
                    "recycling disposal"
                )


            st.link_button(
                (
                    "📍 Find Nearby Disposal "
                    "/ Recycling Option"
                ),

                maps_url(
                    search_query,

                    st.session_state.get(
                        "recycle_location",
                        "",
                    ),
                ),

                use_container_width=True,
            )


            st.caption(
                "Local rules differ. "
                "Confirm what a facility "
                "accepts before visiting."
            )


    show_breakdown(
        [
            item.get(
                "name",
                "",
            )
            for item
            in disposal_items
        ]
    )


# =========================================================
# CHAT
# =========================================================

QUICK_QUESTIONS = [

    "Which idea is easiest?",

    "Can I make this without glue?",

    "What can I finish in 15 minutes?",

    "Can I avoid cutting?",

    "Which idea uses the most materials?",

    "Can a class of 20 students do this?",
]


def show_chat(
    materials,
    result,
    chat_key,
    mode,
):

    if not result:

        return


    st.divider()


    st.header(
        "💬 Ask RecycleAgent AI"
    )


    st.caption(
        "Press Enter or click Send."
    )


    quick_question = None


    with st.expander(
        "⚡ Quick questions",

        expanded=False,
    ):

        columns = st.columns(
            2
        )


        for index, question in enumerate(
            QUICK_QUESTIONS
        ):

            with columns[
                index % 2
            ]:

                if st.button(
                    question,

                    key=(
                        f"{chat_key}"
                        f"_quick_"
                        f"{index}"
                    ),

                    use_container_width=True,
                ):

                    quick_question = (
                        question
                    )


    messages = (
        st.session_state[
            chat_key
        ]
    )


    for message in messages:

        with st.chat_message(
            message[
                "role"
            ]
        ):

            st.markdown(
                message[
                    "content"
                ]
            )


    with st.form(
        f"{chat_key}_form",

        clear_on_submit=True,
    ):

        typed_question = (
            st.text_input(
                "Ask about these reuse ideas",

                placeholder=(
                    "Ask about these "
                    "reuse ideas..."
                ),

                label_visibility=(
                    "collapsed"
                ),
            )
        )


        submitted = (
            st.form_submit_button(
                "Send",

                type="primary",

                use_container_width=True,
            )
        )


    question = (
        quick_question
        or
        (
            typed_question.strip()
            if (
                submitted
                and
                typed_question.strip()
            )
            else
            None
        )
    )


    if not question:

        return


    id_key = (
        f"{chat_key}_id"
    )


    chat_id = (
        st.session_state[
            id_key
        ]
    )


    if chat_id is None:

        chat_id = create_chat(
            mode,
            materials,
            result,
            question,
        )


        st.session_state[
            id_key
        ] = chat_id


    messages.append(
        {
            "role":
                "user",

            "content":
                question,
        }
    )


    save_message(
        chat_id,
        "user",
        question,
    )


    try:

        with st.spinner(
            "Thinking..."
        ):

            answer = ask_ai(
                materials,
                result,
                messages,
                question,
            )


        messages.append(
            {
                "role":
                    "assistant",

                "content":
                    answer,
            }
        )


        save_message(
            chat_id,
            "assistant",
            answer,
        )


        st.rerun()


    except Exception as error:

        st.error(
            "I couldn't answer "
            "that right now."
        )

        st.caption(
            str(error)
        )


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.html(
        """
        <div class="sidebar-brand">

            <div class="ra-logo">

                <span class="ra-recycle">
                    ♻️
                </span>

                <span class="ra-plant">
                    🌱
                </span>

            </div>


            <div class="sidebar-title">
                RecycleAgent AI
            </div>


            <div class="sidebar-tag">
                Reuse what you can.
                Recycle what you can’t.
            </div>

        </div>
        """
    )


    st.divider()


    with st.expander(
        "🎨 Appearance",

        expanded=False,
    ):

        theme_names = list(
            COLOR_THEMES.keys()
        )


        theme_columns = (
            st.columns(2)
        )


        for index, theme_name in enumerate(
            theme_names
        ):

            selected = (
                theme_name
                ==
                st.session_state[
                    "appearance_color"
                ]
            )


            with theme_columns[
                index % 2
            ]:

                if st.button(
                    (
                        "✓ "
                        if selected
                        else
                        ""
                    )
                    +
                    theme_name,

                    key=(
                        f"theme_"
                        f"{index}"
                    ),

                    type=(
                        "primary"
                        if selected
                        else
                        "secondary"
                    ),

                    use_container_width=True,
                ):

                    set_theme(
                        theme_name
                    )

                    st.rerun()


        light_column, dark_column = (
            st.columns(2)
        )


        with light_column:

            if st.button(
                "☀️ Light",

                type=(
                    "primary"
                    if not dark_mode
                    else
                    "secondary"
                ),

                use_container_width=True,
            ):

                set_dark(
                    False
                )

                st.rerun()


        with dark_column:

            if st.button(
                "🌙 Dark",

                type=(
                    "primary"
                    if dark_mode
                    else
                    "secondary"
                ),

                use_container_width=True,
            ):

                set_dark(
                    True
                )

                st.rerun()


    if st.button(
        "❓ Tutorial",

        use_container_width=True,
    ):

        st.session_state[
            "show_tutorial"
        ] = True

        st.rerun()


    if st.button(
        "🎬 Try Demo",

        use_container_width=True,
    ):

        st.session_state[
            "app_mode"
        ] = (
            "✨ What Can I Make?"
        )

        st.session_state[
            "demo_active"
        ] = True

        st.session_state[
            "manual_selected"
        ] = []

        st.session_state[
            "manual_custom"
        ] = ""

        st.session_state[
            "manual_safe_materials"
        ] = [
            {
                "name":
                    "Cardboard",

                "quantity":
                    2,
            },
            {
                "name":
                    "Paper",

                "quantity":
                    5,
            },
            {
                "name":
                    "Bottle caps",

                "quantity":
                    8,
            },
        ]

        st.session_state[
            "manual_result"
        ] = None

        st.session_state[
            "manual_disposal"
        ] = None


        queue_animation(
            [
                "Cardboard",
                "Paper",
                "Bottle caps",
            ]
        )


        st.rerun()


    with st.expander(
        "📍 Nearby Recycling",

        expanded=False,
    ):

        st.text_input(
            "City / postcode (optional)",

            placeholder=(
                "Example: Chennai "
                "or 600001"
            ),

            key="recycle_location",
        )


        st.link_button(
            (
                "♻️ Find Nearby "
                "Recycling Centers"
            ),

            maps_url(
                "recycling center",

                st.session_state[
                    "recycle_location"
                ],
            ),

            use_container_width=True,
        )


        st.caption(
            "If location is blank, Maps "
            "will try a near-me search. "
            "Always confirm what the "
            "facility accepts."
        )


    with st.expander(
        "💬 Chat History",

        expanded=False,
    ):

        chats = list_chats(
            10
        )


        if not chats:

            st.caption(
                "Your saved chats "
                "will appear here."
            )


        for (
            chat_id,
            title,
            chat_mode,
        ) in chats:

            icon = (
                "📷"
                if
                chat_mode
                ==
                "Scan Materials"
                else
                "💡"
            )


            if st.button(
                (
                    icon
                    +
                    " "
                    +
                    title
                ),

                key=(
                    f"history_"
                    f"{chat_id}"
                ),

                use_container_width=True,
            ):

                st.session_state[
                    "history_chat_id"
                ] = chat_id

                st.rerun()


    st.divider()


    if st.button(
        "🏠 Intro Screen",

        use_container_width=True,
    ):

        st.session_state[
            "entered_app"
        ] = False

        st.session_state[
            "history_chat_id"
        ] = None

        st.rerun()


# =========================================================
# MATERIAL ANIMATION
# =========================================================

render_animation()


# =========================================================
# TUTORIAL
# =========================================================

if st.session_state[
    "show_tutorial"
]:

    with st.container(
        border=True
    ):

        st.subheader(
            "❓ How to use RecycleAgent AI"
        )


        tutorial_1, tutorial_2, tutorial_3 = (
            st.columns(3)
        )


        with tutorial_1:

            st.markdown(
                "**1️⃣ Show what you have**"
            )

            st.write(
                "Scan a photo, choose common "
                "materials, or type your own."
            )


        with tutorial_2:

            st.markdown(
                "**2️⃣ AI chooses a route**"
            )

            st.write(
                "Reusable items go to reuse ideas. "
                "Unsuitable items go to safe-disposal "
                "guidance."
            )


        with tutorial_3:

            st.markdown(
                "**3️⃣ Take action**"
            )

            st.write(
                "Follow a build guide, ask questions, "
                "or find an appropriate recycling option."
            )


        if st.button(
            "✓ Got it",

            type="primary",

            use_container_width=True,
        ):

            st.session_state[
                "show_tutorial"
            ] = False

            save_setting(
                "tutorial_seen",
                "true",
            )

            st.rerun()


# =========================================================
# SAVED CHAT VIEW
# =========================================================

if st.session_state[
    "history_chat_id"
]:

    saved_chat = load_chat(
        st.session_state[
            "history_chat_id"
        ]
    )


    if not saved_chat:

        st.session_state[
            "history_chat_id"
        ] = None

        st.rerun()


    top_left, top_right = (
        st.columns(
            [
                4,
                1,
            ]
        )
    )


    with top_left:

        st.caption(
            "💬 SAVED CHAT"
        )

        st.title(
            saved_chat[
                "title"
            ]
        )

        st.caption(
            "From "
            +
            saved_chat[
                "mode"
            ]
        )


    with top_right:

        if st.button(
            "← Back",

            use_container_width=True,
        ):

            st.session_state[
                "history_chat_id"
            ] = None

            st.rerun()


    with st.expander(
        "♻️ Project Context",

        expanded=False,
    ):

        if saved_chat[
            "materials"
        ]:

            for item in saved_chat[
                "materials"
            ]:

                st.write(
                    "• "
                    +
                    str(
                        item.get(
                            "quantity",
                            1,
                        )
                    )
                    +
                    " × "
                    +
                    item.get(
                        "name",
                        "Material",
                    )
                )

        else:

            st.info(
                "This chat started from "
                "general suggestions without "
                "confirmed materials."
            )


        best = (
            saved_chat[
                "result"
            ]
            .get(
                "best_idea",
                {},
            )
        )


        if best:

            st.write(
                "**Project:** "
                +
                best.get(
                    "title",
                    "Reuse project",
                )
            )


    messages = (
        saved_chat[
            "messages"
        ]
    )


    for message in messages:

        with st.chat_message(
            message[
                "role"
            ]
        ):

            st.markdown(
                message[
                    "content"
                ]
            )


    with st.form(
        (
            "saved_form_"
            +
            str(
                saved_chat[
                    "id"
                ]
            )
        ),

        clear_on_submit=True,
    ):

        typed_question = (
            st.text_input(
                "Continue chat",

                placeholder=(
                    "Continue this "
                    "conversation..."
                ),

                label_visibility=(
                    "collapsed"
                ),
            )
        )


        submitted = (
            st.form_submit_button(
                "Send",

                type="primary",

                use_container_width=True,
            )
        )


    if (
        submitted
        and
        typed_question.strip()
    ):

        question = (
            typed_question.strip()
        )


        save_message(
            saved_chat[
                "id"
            ],
            "user",
            question,
        )


        try:

            with st.spinner(
                "Thinking..."
            ):

                answer = ask_ai(
                    saved_chat[
                        "materials"
                    ],

                    saved_chat[
                        "result"
                    ],

                    messages
                    +
                    [
                        {
                            "role":
                                "user",

                            "content":
                                question,
                        }
                    ],

                    question,
                )


            save_message(
                saved_chat[
                    "id"
                ],
                "assistant",
                answer,
            )


            st.rerun()


        except Exception as error:

            st.error(
                "I couldn't answer "
                "that right now."
            )

            st.caption(
                str(error)
            )


    st.divider()


    if st.button(
        "🗑 Delete This Chat"
    ):

        delete_chat(
            saved_chat[
                "id"
            ]
        )

        st.session_state[
            "history_chat_id"
        ] = None

        st.rerun()


    st.stop()


# =========================================================
# MAIN HEADER
# =========================================================

st.html(
    """
    <div class="hero">

        <div class="ra-logo">

            <span class="ra-recycle">
                ♻️
            </span>

            <span class="ra-plant">
                🌱
            </span>

        </div>


        <div>

            <div class="hero-title">
                RecycleAgent AI
            </div>

            <div class="hero-tag">
                Reuse what you can.
                Recycle what you can’t.
            </div>

            <div class="hero-desc">
                See what can become useful before
                deciding what should be thrown away.
            </div>

        </div>

    </div>


    <div class="purpose">

        <strong>
            RecycleAgent AI helps people decide
            what can be reused before deciding
            what should be thrown away.
        </strong>

    </div>
    """
)


journey(
    (
        "detect"
        if
        st.session_state[
            "app_mode"
        ]
        ==
        "📷 Scan Materials"
        else
        "reuse"
    )
)


st.write(
    "**Choose a mode**"
)


choice_buttons(
    [
        "📷 Scan Materials",
        "✨ What Can I Make?",
        "🏫 School Mode",
    ],

    "app_mode",

    "mode",
)


mode = (
    st.session_state[
        "app_mode"
    ]
)


# =========================================================
# MODE 1 — SCAN MATERIALS
# =========================================================

if (
    mode
    ==
    "📷 Scan Materials"
):

    top_left, top_right = (
        st.columns(
            [
                4,
                1,
            ]
        )
    )


    with top_left:

        st.header(
            "📷 Scan Materials"
        )


    with top_right:

        if st.button(
            "🔄 New Scan",

            key="new_scan",

            use_container_width=True,
        ):

            st.session_state[
                "scan_result"
            ] = None

            st.session_state[
                "scan_reuse"
            ] = None

            st.session_state[
                "scan_disposal"
            ] = None

            st.session_state[
                "scan_hash"
            ] = ""

            st.session_state[
                "scan_image_bytes"
            ] = None

            st.session_state[
                "scan_image_name"
            ] = ""

            st.session_state[
                "scan_image_mime"
            ] = "image/jpeg"

            st.session_state[
                "scan_chat"
            ] = []

            st.session_state[
                "scan_chat_id"
            ] = None

            st.session_state[
                "scan_upload_version"
            ] += 1

            st.rerun()


    choice_buttons(
        [
            "Upload an image",
            "Use camera",
        ],

        "photo_method",

        "photo",
    )


    # =====================================================
    # SHOW UPLOADER ONLY BEFORE IMAGE IS STORED
    # =====================================================

    if not st.session_state[
        "scan_image_bytes"
    ]:

        if (
            st.session_state[
                "photo_method"
            ]
            ==
            "Upload an image"
        ):

            upload_key = (
                "scan_uploader_"
                +
                str(
                    st.session_state[
                        "scan_upload_version"
                    ]
                )
            )


            selected_file = (
                st.file_uploader(
                    (
                        "Upload a photo "
                        "of your materials"
                    ),

                    type=[
                        "jpg",
                        "jpeg",
                        "png",
                    ],

                    key=upload_key,
                )
            )


        else:

            upload_key = (
                "scan_camera_"
                +
                str(
                    st.session_state[
                        "scan_upload_version"
                    ]
                )
            )


            selected_file = (
                st.camera_input(
                    (
                        "Take a photo "
                        "of your materials"
                    ),

                    key=upload_key,
                )
            )


        if selected_file is not None:

            try:

                raw = (
                    selected_file.getvalue()
                )


                if not raw:

                    raise ValueError(
                        "The selected "
                        "image was empty."
                    )


                with Image.open(
                    BytesIO(
                        raw
                    )
                ) as check_image:

                    check_image.verify()


                file_name = str(
                    getattr(
                        selected_file,
                        "name",
                        "Uploaded image",
                    )
                )


                mime_type = (
                    getattr(
                        selected_file,
                        "type",
                        None,
                    )
                    or
                    "image/jpeg"
                )


                lower_name = (
                    file_name.lower()
                )


                if mime_type not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                }:

                    if lower_name.endswith(
                        ".png"
                    ):

                        mime_type = (
                            "image/png"
                        )

                    else:

                        mime_type = (
                            "image/jpeg"
                        )


                new_hash = (
                    hashlib.sha256(
                        raw
                    ).hexdigest()
                )


                if (
                    new_hash
                    !=
                    st.session_state[
                        "scan_hash"
                    ]
                ):

                    st.session_state[
                        "scan_result"
                    ] = None

                    st.session_state[
                        "scan_reuse"
                    ] = None

                    st.session_state[
                        "scan_disposal"
                    ] = None

                    st.session_state[
                        "scan_chat"
                    ] = []

                    st.session_state[
                        "scan_chat_id"
                    ] = None


                st.session_state[
                    "scan_hash"
                ] = new_hash

                st.session_state[
                    "scan_image_bytes"
                ] = raw

                st.session_state[
                    "scan_image_name"
                ] = file_name

                st.session_state[
                    "scan_image_mime"
                ] = mime_type


                # Immediately rerun.
                # The uploader disappears on the next run,
                # removing the native black file chip.
                st.rerun()


            except Exception as error:

                st.error(
                    "This file does not appear "
                    "to be a readable image."
                )

                st.caption(
                    str(error)
                )


    # =====================================================
    # STORED IMAGE
    # =====================================================

    raw = (
        st.session_state[
            "scan_image_bytes"
        ]
    )


    if raw:

        file_name = (
            st.session_state[
                "scan_image_name"
            ]
            or
            "Uploaded image"
        )


        mime_type = (
            st.session_state[
                "scan_image_mime"
            ]
            or
            "image/jpeg"
        )


        # IMPORTANT:
        # formatting is done separately on one line.
        # This avoids the previous .1f error.
        file_size_mb = (
            len(raw)
            /
            (
                1024
                *
                1024
            )
        )

        file_size_text = (
            f"{file_size_mb:.1f} MB"
        )


        st.html(
            f"""
            <div class="file-card">

                <div class="file-meta">

                    <div class="file-name">
                        🖼️ {
                            html.escape(
                                file_name
                            )
                        }
                    </div>

                    <div class="file-size">
                        {file_size_text}
                    </div>

                </div>


                <div class="file-ready">
                    ✓ Image ready
                </div>

            </div>
            """
        )


        try:

            preview_image = (
                Image.open(
                    BytesIO(
                        raw
                    )
                )
                .convert(
                    "RGB"
                )
            )


            image_column, scan_column = (
                st.columns(
                    2,
                    gap="large",
                )
            )


            with image_column:

                with st.container(
                    border=True
                ):

                    st.subheader(
                        "Image Preview"
                    )


                    st.image(
                        preview_image,

                        use_container_width=True,
                    )


            with scan_column:

                with st.container(
                    border=True
                ):

                    st.subheader(
                        "AI Material Scan"
                    )


                    st.write(
                        "RecycleAgent AI identifies "
                        "visible materials, estimates "
                        "condition and quantity, and "
                        "checks whether they appear "
                        "suitable for reuse."
                    )


                    st.caption(
                        "Safety is checked before "
                        "anything is sent to the "
                        "reuse-idea generator."
                    )


                    if st.button(
                        "♻️ Analyze Materials",

                        key="analyze_materials",

                        type="primary",

                        use_container_width=True,
                    ):

                        st.session_state[
                            "scan_reuse"
                        ] = None

                        st.session_state[
                            "scan_disposal"
                        ] = None

                        st.session_state[
                            "scan_chat"
                        ] = []

                        st.session_state[
                            "scan_chat_id"
                        ] = None


                        scan_prompt = f"""
You are the computer-vision system
for {APP_NAME}.

Analyze the uploaded image carefully.

Identify visible discarded or leftover
materials that may:

- be suitable for reuse
- be too damaged for reuse
- need safer disposal

Do not invent objects.

Estimate visible quantities.

Confidence must be:

- High
- Medium
- Low

Condition must be:

- Reusable
- Damaged but reusable
- Too damaged to reuse
- Unclear

Safety is more important than reuse.

Do NOT encourage reuse of:

- batteries
- medical waste
- needles
- broken glass
- dangerous sharp objects
- chemicals
- unknown liquids
- contaminated materials
- dangerous electrical components
- flammable materials
- explosive materials

If something may be unsafe:

safe_to_handle = false

Give a short safety_note.

Ignore unrelated background objects.

Do NOT create reuse ideas yet.

Keep material names short and clear.
"""


                        try:

                            image_part = (
                                types.Part.from_bytes(
                                    data=raw,

                                    mime_type=(
                                        mime_type
                                    ),
                                )
                            )


                            with st.spinner(
                                "Looking at your "
                                "materials..."
                            ):

                                result = structured(
                                    scan_prompt,

                                    ScanResult,

                                    temperature=0.1,

                                    image=image_part,
                                )


                            st.session_state[
                                "scan_result"
                            ] = result


                            queue_animation(
                                [
                                    material.get(
                                        "name",
                                        "",
                                    )

                                    for material
                                    in result.get(
                                        "materials",
                                        [],
                                    )

                                    if material.get(
                                        "safe_to_handle",
                                        False,
                                    )
                                ]
                            )


                            st.rerun()


                        except Exception as error:

                            st.error(
                                "RecycleAgent AI "
                                "could not analyze "
                                "this image."
                            )

                            st.caption(
                                str(error)
                            )


        except Exception as error:

            st.error(
                "The stored image "
                "could not be displayed."
            )

            st.caption(
                str(error)
            )


    # =====================================================
    # SCAN RESULTS
    # =====================================================

    scan_result = (
        st.session_state[
            "scan_result"
        ]
    )


    if scan_result:

        st.divider()


        st.header(
            "Materials Detected"
        )


        if scan_result.get(
            "unsafe_material_detected",
            False,
        ):

            banner(
                "unsafe",

                "🛑 Safety warning",

                scan_result.get(
                    "safety_warning",
                    (
                        "A potentially unsafe "
                        "item was detected."
                    ),
                ),
            )


        if scan_result.get(
            "scan_summary"
        ):

            st.info(
                scan_result[
                    "scan_summary"
                ]
            )


        safe_materials = []
        unsafe_materials = []


        materials = (
            scan_result.get(
                "materials",
                [],
            )
        )


        for material in materials:

            name = (
                material.get(
                    "name",
                    "Unknown material",
                )
            )


            quantity = max(
                1,
                int(
                    material.get(
                        "quantity",
                        1,
                    )
                ),
            )


            confidence = (
                material.get(
                    "confidence",
                    "Low",
                )
            )


            condition = (
                material.get(
                    "condition",
                    "Unclear",
                )
            )


            safe_to_handle = (
                material.get(
                    "safe_to_handle",
                    False,
                )
            )


            safety_note = (
                material.get(
                    "safety_note",
                    "",
                )
            )


            with st.expander(
                (
                    emoji_for(
                        name
                    )
                    +
                    " "
                    +
                    name.title()
                ),

                expanded=False,
            ):

                metric_1, metric_2 = (
                    st.columns(2)
                )


                with metric_1:

                    st.metric(
                        "Estimated quantity",

                        quantity,
                    )


                with metric_2:

                    st.metric(
                        "AI confidence",

                        confidence,
                    )


                st.write(
                    "**Condition:** "
                    +
                    condition
                )


                if safe_to_handle:

                    st.success(
                        "Suitable for "
                        "reuse consideration"
                    )

                else:

                    st.error(
                        "Do not use this "
                        "for a reuse project"
                    )


                if safety_note:

                    st.warning(
                        safety_note
                    )


                st.write(
                    "**⏳ Approximate "
                    "decomposition information**"
                )


                st.write(
                    breakdown_text(
                        name
                    )
                )


                st.caption(
                    "Breakdown time varies by "
                    "material and environment."
                )


            if (
                safe_to_handle

                and

                condition
                !=
                "Too damaged to reuse"

                and

                confidence
                !=
                "Low"
            ):

                safe_materials.append(
                    {
                        "name":
                            name,

                        "quantity":
                            quantity,
                    }
                )

            else:

                unsafe_materials.append(
                    {
                        "name":
                            name,

                        "quantity":
                            quantity,

                        "reason":
                            (
                                safety_note
                                or
                                (
                                    "This material "
                                    "was not confidently "
                                    "cleared for reuse."
                                )
                            ),
                    }
                )


        with st.expander(
            "❓ What does AI confidence mean?",

            expanded=False,
        ):

            st.write(
                "**High** — the item is "
                "clearly visible and the "
                "identification appears "
                "relatively strong."
            )


            st.write(
                "**Medium** — the identification "
                "is plausible, but some "
                "uncertainty remains."
            )


            st.write(
                "**Low** — RecycleAgent AI "
                "does not rely on that item "
                "for automatic reuse "
                "recommendations."
            )


            st.warning(
                "AI confidence is not a safety "
                "guarantee. Never handle something "
                "dangerous based only on an AI result."
            )


        show_breakdown(
            [
                material.get(
                    "name",
                    "",
                )

                for material
                in materials
            ]
        )


        # =================================================
        # SAFE DISPOSAL
        # =================================================

        if unsafe_materials:

            st.subheader(
                "🛡️ Items not recommended "
                "for reuse"
            )


            st.write(
                "RecycleAgent AI can provide "
                "general safe-disposal guidance "
                "instead of simply blocking them."
            )


            if st.button(
                "🛡️ Get Safe Disposal Guidance",

                key="scan_disposal_button",

                type="primary",

                use_container_width=True,
            ):

                try:

                    with st.spinner(
                        "Preparing safe-disposal "
                        "guidance..."
                    ):

                        st.session_state[
                            "scan_disposal"
                        ] = generate_disposal(
                            unsafe_materials
                        )


                    st.rerun()


                except Exception as error:

                    st.error(
                        "Could not create "
                        "safe-disposal guidance."
                    )

                    st.caption(
                        str(error)
                    )


        show_disposal(
            st.session_state[
                "scan_disposal"
            ],

            "scan_disposal",
        )


        # =================================================
        # REUSE IDEAS
        # =================================================

        if safe_materials:

            st.divider()


            journey(
                "reuse"
            )


            st.header(
                "✨ What Can These Become?"
            )


            st.write(
                "RecycleAgent AI will use "
                "only the materials that passed "
                "the safety and confidence checks."
            )


            if st.button(
                "✨ Generate Reuse Ideas",

                key="generate_scan_reuse",

                type="primary",

                use_container_width=True,
            ):

                try:

                    st.session_state[
                        "scan_chat"
                    ] = []

                    st.session_state[
                        "scan_chat_id"
                    ] = None


                    with st.spinner(
                        "Finding useful "
                        "reuse ideas..."
                    ):

                        st.session_state[
                            "scan_reuse"
                        ] = generate_reuse(
                            safe_materials
                        )


                    st.rerun()


                except Exception as error:

                    st.error(
                        "RecycleAgent AI could "
                        "not generate reuse ideas."
                    )

                    st.caption(
                        str(error)
                    )


            show_reuse(
                st.session_state[
                    "scan_reuse"
                ],

                "scan",

                True,
            )


            show_chat(
                safe_materials,

                st.session_state[
                    "scan_reuse"
                ],

                "scan_chat",

                "Scan Materials",
            )


        else:

            st.warning(
                "No materials were identified "
                "confidently enough for reuse. "
                "If unsuitable materials were "
                "detected, use the safe-disposal "
                "guidance above."
            )


# =========================================================
# MODE 2 — WHAT CAN I MAKE?
# =========================================================

elif (
    mode
    ==
    "✨ What Can I Make?"
):

    st.header(
        "✨ What Can I Make?"
    )


    st.write(
        "Choose materials you have, "
        "type your own, or ask for "
        "ideas without selecting anything."
    )


    # =====================================================
    # DEMO MODE
    # =====================================================

    if st.session_state[
        "demo_active"
    ]:

        banner(
            "reuse",

            "🎬 Demo Mode — Sample Data",

            (
                "This is prepared sample data "
                "for demonstrating the app. "
                "It is not a camera scan."
            ),
        )


        demo_materials = (
            st.session_state[
                "manual_safe_materials"
            ]
        )


        for item in demo_materials:

            st.write(
                "• "
                +
                str(
                    item[
                        "quantity"
                    ]
                )
                +
                " × "
                +
                item[
                    "name"
                ]
            )


        if st.button(
            "✨ Run Demo Suggestions",

            type="primary",

            use_container_width=True,
        ):

            try:

                with st.spinner(
                    "Generating demo ideas..."
                ):

                    st.session_state[
                        "manual_result"
                    ] = generate_reuse(
                        demo_materials
                    )

                    st.session_state[
                        "manual_kind"
                    ] = "inventory"

                    st.session_state[
                        "manual_chat"
                    ] = []

                    st.session_state[
                        "manual_chat_id"
                    ] = None


                st.rerun()


            except Exception as error:

                st.error(
                    "Could not generate "
                    "demo suggestions."
                )

                st.caption(
                    str(error)
                )


        if st.button(
            "Exit Demo",

            use_container_width=True,
        ):

            st.session_state[
                "demo_active"
            ] = False

            st.session_state[
                "manual_result"
            ] = None

            st.session_state[
                "manual_safe_materials"
            ] = []

            st.rerun()


        materials_for_result = (
            demo_materials
        )


    # =====================================================
    # NORMAL MANUAL MODE
    # =====================================================

    else:

        (
            material_names,
            typed_materials,
        ) = material_picker(
            "manual",

            "What do you have?",
        )


        manual_materials = []


        if material_names:

            st.subheader(
                "How much do you have?"
            )


            quantity_columns = (
                st.columns(3)
            )


            for index, name in enumerate(
                material_names
            ):

                with quantity_columns[
                    index % 3
                ]:

                    with st.container(
                        border=True
                    ):

                        quantity = stepper(
                            name,

                            (
                                "manual_qty_"
                                +
                                safe_key(
                                    name
                                )
                            ),

                            1,

                            1,

                            100,
                        )


                        manual_materials.append(
                            {
                                "name":
                                    name,

                                "quantity":
                                    quantity,
                            }
                        )


        signature = (
            hashlib.sha256(
                json.dumps(
                    manual_materials,

                    sort_keys=True,
                ).encode(
                    "utf-8"
                )
            ).hexdigest()
        )


        if (
            signature
            !=
            st.session_state[
                "manual_signature"
            ]
        ):

            st.session_state[
                "manual_signature"
            ] = signature

            st.session_state[
                "manual_result"
            ] = None

            st.session_state[
                "manual_disposal"
            ] = None

            st.session_state[
                "manual_safe_materials"
            ] = []

            st.session_state[
                "manual_chat"
            ] = []

            st.session_state[
                "manual_chat_id"
            ] = None


        if manual_materials:

            show_breakdown(
                [
                    item[
                        "name"
                    ]
                    for item
                    in manual_materials
                ]
            )


            if st.button(
                (
                    "♻️ Find Reuse / "
                    "Safe Disposal Options"
                ),

                type="primary",

                use_container_width=True,
            ):

                selected_lower = {
                    item.lower()
                    for item
                    in st.session_state[
                        "manual_selected"
                    ]
                }


                common_safe = [
                    item
                    for item
                    in manual_materials
                    if item[
                        "name"
                    ].lower()
                    in selected_lower
                ]


                custom_materials = [
                    item
                    for item
                    in manual_materials
                    if item[
                        "name"
                    ].lower()
                    not in selected_lower
                ]


                safe_materials = list(
                    common_safe
                )


                unsafe_materials = []


                try:

                    with st.spinner(
                        "Checking safety "
                        "and finding the "
                        "best route..."
                    ):

                        if custom_materials:

                            assessment = (
                                assess_materials(
                                    custom_materials
                                )
                            )


                            assessment_map = {

                                item.get(
                                    "name",
                                    "",
                                ).lower():
                                    item

                                for item
                                in assessment.get(
                                    "materials",
                                    [],
                                )
                            }


                            for item in custom_materials:

                                assessment_item = (
                                    assessment_map.get(
                                        item[
                                            "name"
                                        ].lower()
                                    )
                                )


                                if (
                                    assessment_item
                                    and
                                    assessment_item.get(
                                        "safe_for_reuse",
                                        False,
                                    )
                                ):

                                    safe_materials.append(
                                        item
                                    )

                                else:

                                    unsafe_materials.append(
                                        {
                                            "name":
                                                item[
                                                    "name"
                                                ],

                                            "quantity":
                                                item[
                                                    "quantity"
                                                ],

                                            "reason":
                                                (
                                                    assessment_item.get(
                                                        "reason",
                                                        "",
                                                    )
                                                    if assessment_item
                                                    else
                                                    (
                                                        "Not confidently "
                                                        "cleared for reuse."
                                                    )
                                                ),
                                        }
                                    )


                        st.session_state[
                            "manual_safe_materials"
                        ] = safe_materials


                        if safe_materials:

                            st.session_state[
                                "manual_result"
                            ] = generate_reuse(
                                safe_materials
                            )

                        else:

                            st.session_state[
                                "manual_result"
                            ] = None


                        if unsafe_materials:

                            st.session_state[
                                "manual_disposal"
                            ] = generate_disposal(
                                unsafe_materials
                            )

                        else:

                            st.session_state[
                                "manual_disposal"
                            ] = None


                        st.session_state[
                            "manual_kind"
                        ] = "inventory"

                        st.session_state[
                            "manual_chat"
                        ] = []

                        st.session_state[
                            "manual_chat_id"
                        ] = None


                    st.rerun()


                except Exception as error:

                    st.error(
                        "Could not assess "
                        "these materials."
                    )

                    st.caption(
                        str(error)
                    )


        else:

            st.subheader(
                "Don't know what to use?"
            )


            if st.button(
                (
                    "💡 Suggest Ideas "
                    "Without Materials"
                ),

                type="primary",

                use_container_width=True,
            ):

                try:

                    with st.spinner(
                        "Thinking of useful "
                        "possibilities..."
                    ):

                        st.session_state[
                            "manual_result"
                        ] = generate_general_reuse()

                        st.session_state[
                            "manual_disposal"
                        ] = None

                        st.session_state[
                            "manual_safe_materials"
                        ] = []

                        st.session_state[
                            "manual_kind"
                        ] = "suggested"

                        st.session_state[
                            "manual_chat"
                        ] = []

                        st.session_state[
                            "manual_chat_id"
                        ] = None


                    st.rerun()


                except Exception as error:

                    st.error(
                        "Could not generate "
                        "suggestions."
                    )

                    st.caption(
                        str(error)
                    )


        materials_for_result = (
            st.session_state[
                "manual_safe_materials"
            ]
        )


    show_disposal(
        st.session_state[
            "manual_disposal"
        ],

        "manual_disposal",
    )


    inventory_known = (
        st.session_state[
            "manual_kind"
        ]
        ==
        "inventory"
    )


    show_reuse(
        st.session_state[
            "manual_result"
        ],

        "manual",

        inventory_known,
    )


    if st.session_state[
        "manual_result"
    ]:

        if st.session_state[
            "demo_active"
        ]:

            chat_mode = (
                "Demo Mode"
            )

        elif inventory_known:

            chat_mode = (
                "What Can I Make?"
            )

        else:

            chat_mode = (
                "Open Suggestions"
            )


        show_chat(
            (
                materials_for_result
                if inventory_known
                else
                []
            ),

            st.session_state[
                "manual_result"
            ],

            "manual_chat",

            chat_mode,
        )


# =========================================================
# MODE 3 — SCHOOL MODE
# =========================================================

else:

    st.header(
        "🏫 School Mode"
    )


    st.write(
        "Plan a reuse activity "
        "using safe leftover "
        "classroom materials."
    )


    with st.container(
        border=True
    ):

        class_size = stepper(
            (
                "How many students "
                "are in the class?"
            ),

            "school_class_size",

            20,

            1,

            60,

            True,
        )


    (
        school_names,
        school_typed,
    ) = material_picker(
        "school",

        (
            "What classroom materials "
            "are available?"
        ),
    )


    school_materials = []


    if school_names:

        st.subheader(
            "Classroom Inventory"
        )


        quantity_columns = (
            st.columns(3)
        )


        for index, name in enumerate(
            school_names
        ):

            with quantity_columns[
                index % 3
            ]:

                with st.container(
                    border=True
                ):

                    quantity = stepper(
                        name,

                        (
                            "school_qty_"
                            +
                            safe_key(
                                name
                            )
                        ),

                        5,

                        1,

                        500,
                    )


                    school_materials.append(
                        {
                            "name":
                                name,

                            "quantity":
                                quantity,
                        }
                    )


    school_signature = (
        hashlib.sha256(
            json.dumps(
                {
                    "class":
                        class_size,

                    "materials":
                        school_materials,
                },

                sort_keys=True,
            ).encode(
                "utf-8"
            )
        ).hexdigest()
    )


    if (
        school_signature
        !=
        st.session_state[
            "school_signature"
        ]
    ):

        st.session_state[
            "school_signature"
        ] = school_signature

        st.session_state[
            "school_plan"
        ] = None

        st.session_state[
            "school_disposal"
        ] = None


    if school_materials:

        show_breakdown(
            [
                item[
                    "name"
                ]
                for item
                in school_materials
            ]
        )


        if st.button(
            "🏫 Create Class Reuse Plan",

            type="primary",

            use_container_width=True,
        ):

            selected_lower = {
                item.lower()
                for item
                in st.session_state[
                    "school_selected"
                ]
            }


            common_safe = [
                item
                for item
                in school_materials
                if item[
                    "name"
                ].lower()
                in selected_lower
            ]


            custom_materials = [
                item
                for item
                in school_materials
                if item[
                    "name"
                ].lower()
                not in selected_lower
            ]


            safe_materials = list(
                common_safe
            )

            unsafe_materials = []


            try:

                with st.spinner(
                    "Checking materials "
                    "and planning the "
                    "class project..."
                ):

                    if custom_materials:

                        assessment = (
                            assess_materials(
                                custom_materials
                            )
                        )


                        assessment_map = {

                            item.get(
                                "name",
                                "",
                            ).lower():
                                item

                            for item
                            in assessment.get(
                                "materials",
                                [],
                            )
                        }


                        for item in custom_materials:

                            assessment_item = (
                                assessment_map.get(
                                    item[
                                        "name"
                                    ].lower()
                                )
                            )


                            if (
                                assessment_item
                                and
                                assessment_item.get(
                                    "safe_for_reuse",
                                    False,
                                )
                            ):

                                safe_materials.append(
                                    item
                                )

                            else:

                                unsafe_materials.append(
                                    {
                                        "name":
                                            item[
                                                "name"
                                            ],

                                        "quantity":
                                            item[
                                                "quantity"
                                            ],

                                        "reason":
                                            (
                                                assessment_item.get(
                                                    "reason",
                                                    "",
                                                )
                                                if assessment_item
                                                else
                                                (
                                                    "Not cleared "
                                                    "for reuse."
                                                )
                                            ),
                                    }
                                )


                    if safe_materials:

                        school_plan = (
                            generate_school(
                                safe_materials,

                                class_size,
                            )
                        )


                        st.session_state[
                            "school_plan"
                        ] = validate_school_plan(
                            safe_materials,

                            school_plan,
                        )

                    else:

                        st.session_state[
                            "school_plan"
                        ] = None


                    if unsafe_materials:

                        st.session_state[
                            "school_disposal"
                        ] = generate_disposal(
                            unsafe_materials
                        )

                    else:

                        st.session_state[
                            "school_disposal"
                        ] = None


                st.rerun()


            except Exception as error:

                st.error(
                    "Could not create "
                    "a valid classroom plan."
                )

                st.caption(
                    str(error)
                )


    else:

        st.info(
            "Choose or type at least "
            "one classroom material."
        )


    show_disposal(
        st.session_state[
            "school_disposal"
        ],

        "school_disposal",
    )


    school_plan = (
        st.session_state[
            "school_plan"
        ]
    )


    if school_plan:

        project = (
            school_plan.get(
                "project",
                {},
            )
        )


        st.divider()


        banner(
            "reuse",

            "🏫 Class reuse route",

            (
                "This project uses "
                "classroom materials "
                "cleared for reuse."
            ),
        )


        st.header(
            project.get(
                "title",
                "Class Reuse Project",
            )
        )


        badges(
            project.get(
                "best_for",
                [],
            )
        )


        why_chosen = (
            project.get(
                "why_chosen",
                "",
            )
        )


        if why_chosen:

            st.html(
                f"""
                <div class="why">

                    <strong>
                        ✨ Why {APP_NAME} chose this:
                    </strong>

                    <br>

                    {
                        html.escape(
                            why_chosen
                        )
                    }

                </div>
                """
            )


        group_size = max(
            1,
            int(
                project.get(
                    "group_size",
                    1,
                )
            ),
        )


        groups_supported = max(
            1,
            int(
                project.get(
                    "groups_supported",
                    1,
                )
            ),
        )


        students_supported = min(
            class_size,

            group_size
            *
            groups_supported,
        )


        metric_1, metric_2, metric_3, metric_4 = (
            st.columns(4)
        )


        with metric_1:

            st.metric(
                "Group size",

                group_size,
            )


        with metric_2:

            st.metric(
                "Groups possible",

                groups_supported,
            )


        with metric_3:

            st.metric(
                "Students involved",

                students_supported,
            )


        with metric_4:

            st.metric(
                "Estimated time",

                project.get(
                    "estimated_time",
                    "Unknown",
                ),
            )


        with st.expander(
            "📝 Project overview",

            expanded=False,
        ):

            st.write(
                project.get(
                    "description",
                    "",
                )
            )


        with st.expander(
            "📦 Materials Used Per Group",

            expanded=False,
        ):

            for item in project.get(
                "materials_per_group",
                [],
            ):

                st.write(
                    "• "
                    +
                    str(
                        item.get(
                            "quantity_per_group",
                            0,
                        )
                    )
                    +
                    " × "
                    +
                    item.get(
                        "name",
                        "Material",
                    )
                )


        with st.expander(
            "📖 Class Build Guide",

            expanded=False,
        ):

            for number, step in enumerate(
                project.get(
                    "steps",
                    [],
                ),
                start=1,
            ):

                st.markdown(
                    f"**{number}.** "
                    f"{step}"
                )


        with st.expander(
            "🧰 Tools & Extra Materials",

            expanded=False,
        ):

            tools = (
                project.get(
                    "tools_needed",
                    [],
                )
            )


            extras = (
                project.get(
                    "additional_materials",
                    [],
                )
            )


            st.write(
                "**Tools:** "
                +
                (
                    ", ".join(
                        tools
                    )
                    if tools
                    else
                    "None"
                )
            )


            st.write(
                "**Extras:** "
                +
                (
                    ", ".join(
                        extras
                    )
                    if extras
                    else
                    "None"
                )
            )


        with st.expander(
            (
                "⚠️ Safety, Learning "
                "& Environmental Value"
            ),

            expanded=False,
        ):

            for note in project.get(
                "safety_notes",
                [],
            ):

                st.warning(
                    note
                )


            st.write(
                "**Educational value**"
            )


            st.write(
                project.get(
                    "educational_value",
                    "",
                )
            )


            st.write(
                "**Environmental benefit**"
            )


            st.write(
                project.get(
                    "environmental_benefit",
                    "",
                )
            )


        if school_plan.get(
            "class_message"
        ):

            st.info(
                school_plan[
                    "class_message"
                ]
            )


        search_query = (
            project.get(
                "video_search_query",
                "",
            )
        )


        if search_query:

            st.link_button(
                (
                    "▶️ Find Similar "
                    "Class Tutorial"
                ),

                (
                    "https://www.youtube.com/"
                    "results?search_query="
                    +
                    quote_plus(
                        search_query
                    )
                ),

                use_container_width=True,
            )


# =========================================================
# FOOTER
# =========================================================

st.divider()


st.caption(
    f"{APP_NAME} uses artificial intelligence. "
    "Material detection, quantities, reuse ideas, "
    "disposal guidance, build instructions, chat "
    "answers and classroom plans may be incorrect. "
    "Local recycling and hazardous-waste rules differ. "
    "Never handle potentially dangerous waste based "
    "only on an AI result."
)