#!/usr/bin/env python3
"""KodiTV Legal Hub — unified builder.

Subcommands:
    build   (default)  download playlist, write Kodi configs
    sync               refresh playlist + EPG (for cron / Task Scheduler)
    roms               download public-domain ROMs from Internet Archive

Flags:
    --install          after build, copy configs into detected Kodi userdata
    --roms             after build, also run the ROM downloader
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

FREE_IPTV_URLS = [
    "https://iptv-org.github.io/iptv/index.m3u",
    "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "https://iptv-org.github.io/iptv/categories/music.m3u",
    "https://iptv-org.github.io/iptv/categories/news.m3u",
    "https://iptv-org.github.io/iptv/categories/sports.m3u",
]

RECOMMENDED_ADDONS = [
    ("plugin.video.youtube",        "YouTube — free content & PD movies"),
    ("plugin.video.plutotv",        "Pluto TV — free, ad-supported"),
    ("plugin.video.tubi",           "Tubi — free, ad-supported"),
    ("pvr.iptvsimple",              "IPTV Simple Client — live TV"),
    ("plugin.audio.radio_de",       "Radio.de — 100k+ stations"),
    ("game.libretro",               "RetroArch core loader"),
    ("game.libretro.mame2003_plus", "Arcade — public-domain ROMsets"),
]

ROM_COLLECTIONS = {
    "atari_2600":  "atari_2600",
    "atari_7800":  "atari_7800",
    "colecovision": "colecovision",
    "odyssey2":    "odyssey2",
}
ROM_BASE = "https://archive.org/download/consolelivingroom/"

# ---------- helpers ----------

def fetch(url: str, timeout: int = 30) -> str:
    print(f"  ↳ fetching {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "koditv-legal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def kodi_userdata_paths() -> list[Path]:
    sysname = platform.system()
    home = Path.home()
    out = []
    if sysname == "Linux":
        out.append(home / ".kodi" / "userdata")
    elif sysname == "Darwin":
        out.append(home / "Library" / "Application Support" / "Kodi" / "userdata")
    elif sysname == "Windows":
        ad = os.environ.get("APPDATA")
        if ad:
            out.append(Path(ad) / "Kodi" / "userdata")
    out.append(Path("/sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata"))
    return out

def kodi_rom_root() -> Path:
    for p in kodi_userdata_paths():
        candidate = (p / "addon_data" / "game.libretro.mame2003_plus"
                     / "resources" / "roms")
        if candidate.parent.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    fallback = Path.home() / "koditv-roms"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

# ---------- playlist ----------

def merge_playlist() -> Path:
    out = ROOT / "playlists" / "free_iptv.m3u"
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(out, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for url in FREE_IPTV_URLS:
            try:
                text = fetch(url)
            except Exception as e:
                print(f"  [!] skipped {url}: {e}")
                continue
            body = text.replace("#EXTM3U", "", 1).lstrip()
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")
            total += body.count("#EXTINF")
    print(f"[✓] playlist: {out}  ({total} channels)")
    return out

# ---------- kodi config ----------

def write_kodi_config() -> Path:
    cfg = ROOT / "kodi_config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "advancedsettings.xml").write_text(
        "<advancedsettings>\n"
        "  <network>\n"
        "    <buffermode>1</buffermode>\n"
        "    <cachemembuffersize>52428800</cachemembuffersize>\n"
        "    <readbufferfactor>4.0</readbufferfactor>\n"
        "  </network>\n"
        "</advancedsettings>\n",
        encoding="utf-8",
    )
    (cfg / "sources.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<sources>\n"
        "  <video>\n"
        '    <default pathversion="1"/>\n'
        "    <source>\n"
        "      <name>Internet Archive (Public Domain)</name>\n"
        '      <path pathversion="1">https://archive.org/download/</path>\n'
        "      <allowsharing>true</allowsharing>\n"
        "    </source>\n"
        "    <source>\n"
        "      <name>Free IPTV</name>\n"
        '      <path pathversion="1">plugin://pvr.iptvsimple</path>\n'
        "    </source>\n"
        "  </video>\n"
        "  <music>\n"
        '    <default pathversion="1"/>\n'
        "    <source>\n"
        "      <name>Radio.de</name>\n"
        '      <path pathversion="1">plugin://plugin.audio.radio_de</path>\n'
        "    </source>\n"
        "  </music>\n"
        "  <games>\n"
        '    <default pathversion="1"/>\n'
        "  </games>\n"
        "</sources>\n",
        encoding="utf-8",
    )
    print(f"[✓] kodi_config: {cfg}")
    return cfg

# ---------- install into Kodi userdata ----------

def install(cfg: Path, playlist: Path) -> None:
    target = next((p for p in kodi_userdata_paths() if p.exists()), None)
    if target is None:
        print("[!] Kodi userdata folder not found. Copy kodi_config/ and")
        print("    playlists/ manually, or install Kodi first.")
        return

    print(f"[→] installing into {target}")
    for fname in ("advancedsettings.xml", "sources.xml"):
        src, dst = cfg / fname, target / fname
        if dst.exists():
            shutil.copy2(dst, dst.with_suffix(dst.suffix + ".bak"))
        shutil.copy2(src, dst)
        print(f"    {dst}")

    epg_file = ROOT / "epg" / "guide.xml"
    addon_data = target / "addon_data" / "pvr.iptvsimple"
    addon_data.mkdir(parents=True, exist_ok=True)
    settings = addon_data / "instance-settings-1.xml"
    settings.write_text(
        '<settings version="2">\n'
        '  <setting id="m3uPathType">0</setting>\n'
        f'  <setting id="m3uPath">{playlist}</setting>\n'
        '  <setting id="startNum">1</setting>\n'
        '  <setting id="epgPathType">0</setting>\n'
        f'  <setting id="epgPath">{epg_file if epg_file.exists() else ""}</setting>\n'
        "</settings>\n",
        encoding="utf-8",
    )
    print(f"    wired IPTV Simple → {playlist}")
    if epg_file.exists():
        print(f"    wired EPG → {epg_file}")
    else:
        print("[!] no EPG file yet — run `build.py sync` once")

# ---------- EPG ----------

def grab_epg() -> Path | None:
    script = ROOT / "epg" / "grab_epg.sh"
    if not script.exists():
        print("[!] epg/grab_epg.sh missing — skipping EPG")
        return None
    print("[*] refreshing EPG")
    subprocess.run(["bash", str(script)], check=False)
    out = ROOT / "epg" / "guide.xml"
    return out if out.exists() else None

# ---------- ROMs ----------

def install_roms() -> None:
    dest = kodi_rom_root()
    print(f"[→] ROM destination: {dest}")
    for name, ident in ROM_COLLECTIONS.items():
        sub = dest / name
        sub.mkdir(exist_ok=True)
        url = f"{ROM_BASE}{ident}/"
        try:
            with urllib.request.urlopen(url + "files.json", timeout=30) as r:
                files = json.loads(r.read()).get("files", [])
        except Exception as e:
            print(f"[!] {name}: listing failed ({e})")
            continue
        got = 0
        for f in files:
            fn = f["name"]
            if not fn.lower().endswith((".zip", ".rom", ".bin", ".a26", ".col")):
                continue
            out = sub / fn
            if out.exists():
                continue
            try:
                with urllib.request.urlopen(url + fn, timeout=60) as r, \
                     open(out, "wb") as fh:
                    shutil.copyfileobj(r, fh)
                got += 1
            except Exception as e:
                print(f"    [!] {fn}: {e}")
        print(f"[✓] {name}: {got} new files")
    print("Next: Kodi → Games → MAME 2003+ → Add ROMs → "
          f"{dest}")

# ---------- commands ----------

def cmd_build(args) -> int:
    print("[*] building KodiTV Legal Hub")
    playlist = merge_playlist()
    cfg = write_kodi_config()
    if args.install:
        install(cfg, playlist)
    if args.roms:
        install_roms()
    print_next_steps()
    return 0

def cmd_sync(_args) -> int:
    print("[*] sync: playlist")
    merge_playlist()
    print("[*] sync: EPG")
    grab_epg()
    return 0

def cmd_roms(_args) -> int:
    install_roms()
    return 0

def print_next_steps() -> None:
    print("\n=== Next steps ===")
    print("1. Start Kodi.")
    print("2. Settings → PVR & Live TV → General → Enable = ON")
    print("3. Add-ons → Install from repository → Kodi Add-on Repository:")
    for aid, desc in RECOMMENDED_ADDONS:
        print(f"     • {aid:<32} {desc}")
    print("4. Restart Kodi. Live TV / Movies / Music / Games appear.")
    print("5. Weekly refresh: `python3 build.py sync` (cron / Task Scheduler).")
    print()

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="build",
                    choices=["build", "sync", "roms"])
    ap.add_argument("--install", action="store_true",
                    help="copy configs into detected Kodi userdata folder")
    ap.add_argument("--roms", action="store_true",
                    help="also download public-domain ROMs after build")
    args = ap.parse_args()

    return {"build": cmd_build, "sync": cmd_sync, "roms": cmd_roms}[args.command](args)

if __name__ == "__main__":
    sys.exit(main())
