"""
routers/reference.py — Static D&D data reference endpoints.
These read directly from the data files via a freshly-loaded StateManager,
without creating a real session.

GET /api/reference/classes
GET /api/reference/races
GET /api/reference/npcs
GET /api/reference/weapons
GET /api/reference/armor
GET /api/reference/spells
"""
import os
from functools import lru_cache

import yaml
from fastapi import APIRouter

router = APIRouter()

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)


@lru_cache(maxsize=1)
def _load_dir(subdir: str) -> dict:
    path = os.path.join(_DATA_DIR, subdir)
    result = {}
    if os.path.isdir(path):
        for fname in sorted(os.listdir(path)):
            if fname.endswith(".yaml"):
                with open(os.path.join(path, fname)) as f:
                    result[fname.removesuffix(".yaml")] = yaml.safe_load(f) or {}
    return result


@lru_cache(maxsize=1)
def _load_file(relpath: str) -> dict:
    path = os.path.join(_DATA_DIR, relpath)
    if os.path.isfile(path):
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


@router.get("/reference/classes")
def get_classes():
    """D&D 5e class data (hit die, skills, equipment, spells)."""
    return _load_dir("char_classes")


@router.get("/reference/races")
def get_races():
    """D&D 5e race data (attribute bonuses, traits, subraces)."""
    return _load_dir("races")


@router.get("/reference/npcs")
def get_npcs():
    """NPC/monster templates (HP, AC, actions, XP)."""
    return _load_dir("npcs")


@router.get("/reference/weapons")
def get_weapons():
    """Weapon stat blocks (damage, type, properties)."""
    return _load_file("items/weapons.yaml")


@router.get("/reference/armor")
def get_armor():
    """Armour stat blocks (AC, DEX cap)."""
    return _load_file("items/armor.yaml")


@router.get("/reference/spells")
def get_spells():
    """Spell data (level, damage, type, save)."""
    return _load_file("items/spells.yaml")
