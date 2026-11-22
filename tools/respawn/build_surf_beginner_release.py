#!/usr/bin/env python3
"""Build the Surf Beginner Northstar mod and Thunderstore release package."""

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from build_minecraft_ports import build_loadscreen


MOD = "MRVN.SourceSurfBeginner"
LEVEL = "mp_source_surf_beginner"
VERSION = "0.2.0"

TRANSLATIONS = {
    "english": ("Surf Beginner", "A seven-stage beginner surf course. Play Surf mode for timed runs through all seven stages."),
    "french": ("Surf Débutant", "Un parcours surf débutant en sept étapes. Jouez en mode Surf pour chronométrer les sept étapes."),
    "german": ("Surf-Einsteiger", "Ein siebenstufiger Surf-Anfängerkurs. Spiele den Surf-Modus für zeitlich gemessene Durchläufe aller sieben Etappen."),
    "italian": ("Surf per principianti", "Un percorso surf per principianti in sette tappe. Gioca in modalità Surf per completare cronometricamente tutte le tappe."),
    "spanish": ("Surf para principiantes", "Un curso surf para principiantes con siete etapas. Juega en modo Surf para cronometrar las siete etapas."),
    "russian": ("Сёрф для новичков", "Курс сёрфинга для новичков из семи этапов. Пройдите все этапы в режиме Surf на время."),
    "japanese": ("サーフ ビギナー", "初心者向けの7ステージサーフコース。Surfモードですべてのステージをタイムアタックで進みます。"),
    "polish": ("Surf dla początkujących", "Siedmioetapowy kurs surf dla początkujących. Graj w trybie Surf i przechodź wszystkie etapy na czas."),
    "portuguese": ("Surf Iniciante", "Um curso surf para iniciantes com sete etapas. Jogue no modo Surf para fazer corridas cronometradas pelas sete etapas."),
    "tchinese": ("新手衝浪", "七關卡的初學者衝浪地圖。在 Surf 模式中計時完成全部關卡。"),
    "schinese": ("新手冲浪", "七个阶段的初学者冲浪地图。在 Surf 模式中计时完成全部关卡。"),
}


def utf16_text(path, language, name, description):
    body = (
        '"lang"\n{\n'
        f'\t"Language" "{language}"\n'
        '\t"Tokens"\n\t{\n'
        f'\t\t"{LEVEL}" "{name}"\n'
        f'\t\t"{LEVEL}_ALLCAPS" "{name.upper()}"\n'
        f'\t\t"{LEVEL}_CLASSIC" "{name}"\n'
        f'\t\t"{LEVEL}_CLASSIC_DESC" "{description}"\n'
        f'\t\t"{LEVEL}_DESC" "{description}"\n'
        '\t}\n}\n'
    )
    path.write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))


def font(size, bold=False):
    base = "C:/Windows/Fonts/"
    candidates = (("arialbd.ttf", "arial.ttf") if bold else ("arial.ttf", "arialbd.ttf"))
    for name in candidates:
        path = base + name
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_assets(source_shot, release):
    release.mkdir(parents=True, exist_ok=True)
    shot = Image.open(source_shot).convert("RGB")
    loading = ImageOpsFit(shot, (1920, 1080))
    draw = ImageDraw.Draw(loading)
    draw.rectangle((0, 820, 1920, 1080), fill=(18, 20, 24, 210))
    draw.text((100, 865), "SURF BEGINNER", font=font(78, True), fill=(255, 255, 255))
    draw.text((104, 960), "Seven stages. One run.", font=font(38), fill=(210, 214, 220))
    loading.save(release / "loading-screen.png")

    icon = ImageOpsFit(shot, (256, 256))
    draw = ImageDraw.Draw(icon)
    draw.rectangle((0, 176, 256, 256), fill=(18, 20, 24, 225))
    draw.text((128, 214), "SURF", anchor="mm", font=font(38, True), fill=(255, 255, 255))
    icon.save(release / "icon.png")
    return loading


def ImageOpsFit(image, size):
    # Local crop/scale equivalent for a stable 16:9 or square promotional image.
    from PIL import ImageOps
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def zip_directory(folder, archive):
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.resolve() != archive.resolve():
                output.write(path, path.relative_to(folder).as_posix())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--shot", type=Path, required=True)
    parser.add_argument("--repak", type=Path, required=True)
    parser.add_argument("--loadscreen-template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.shot = args.shot.resolve()
    args.repak = args.repak.resolve()
    args.loadscreen_template = args.loadscreen_template.resolve()
    args.output = args.output.resolve()

    if args.output.exists():
        raise ValueError(f"output already exists: {args.output}")
    shutil.copytree(args.source, args.output)

    mod = args.output
    mod_json = json.loads((mod / "mod.json").read_text())
    mod_json.update({
        "Name": MOD,
        "Version": VERSION,
        "Description": "Surf Beginner - a seven-stage beginner surf course",
    })
    mod_json["Localisation"] = ["resource/mp_source_surf_beginner_%language%.txt"]
    (mod / "mod.json").write_text(json.dumps(mod_json, indent=2) + "\n")

    resource = mod / "mod" / "resource"
    resource.mkdir(parents=True, exist_ok=True)
    for old in resource.glob("mp_source_surf_beginner_*.txt"):
        old.unlink()
    for language, (name, description) in TRANSLATIONS.items():
        utf16_text(resource / f"{LEVEL}_{language}.txt", language, name, description)

    draw_assets(args.shot, mod)

    loading = mod / "loading-screen.png"
    build_args = SimpleNamespace(
        loadscreen=loading,
        loadscreen_template=args.loadscreen_template,
        repak=args.repak,
    )
    loadscreen_rpak = build_loadscreen(mod, build_args, LEVEL)
    (mod / "paks").mkdir(exist_ok=True)
    shutil.copyfile(loadscreen_rpak, mod / "paks" / f"{LEVEL}_loadscreen.rpak")
    (mod / "paks" / "rpak.json").write_text(json.dumps({
        "Aliases": {f"{LEVEL}.rpak": "mp_coliseum.rpak"}
    }, indent=2) + "\n")

    readme = mod / "README.md"
    readme.write_text(
        "# Surf Beginner\n\n"
        "A Northstar port of the Counter-Strike: Source map `surf_beginner`, "
        "with seven stage checkpoints, timed runs, teleports, and reset controls.\n\n"
        "## Install\n\n"
        "Requires the Surf mode mod version 0.2.0 or later.\n"
        "Extract `MRVN.SourceSurfBeginner` into your Northstar `mods` folder.\n\n"
        "## Play\n\n"
        "Start a local match and run:\n\n"
        "```text\n"
        f"map {LEVEL} surf\n"
        "```\n\n"
        "Use the boost/reset key to return to the stage 1 start platform.\n"
    )

    thunder = args.output.parent / f"{args.output.name}-thunderstore"
    if thunder.exists():
        raise ValueError(f"Thunderstore output already exists: {thunder}")
    thunder.mkdir()
    shutil.copyfile(mod / "icon.png", thunder / "icon.png")
    shutil.copyfile(readme, thunder / "README.md")
    shutil.copytree(mod, thunder / mod.name)
    manifest = {
        "name": "SourceSurfBeginner",
        "version_number": VERSION,
        "website_url": "https://github.com/taskinoz/MRVN-Radiant",
        "description": "Seven-stage Surf Beginner map port for Titanfall 2 Northstar.",
        "dependencies": ["Northstar-Northstar@1.35.0"],
    }
    (thunder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    zip_directory(thunder, thunder / f"{MOD}-{VERSION}.zip")

    print(json.dumps({
        "mod": str(mod),
        "thunderstore": str(thunder),
        "mod_zip": str(thunder / f"{MOD}-{VERSION}.zip"),
    }, indent=2))


if __name__ == "__main__":
    main()
