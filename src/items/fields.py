"""Editor presentation for item attributes: labels, groups and unit conversions."""
from __future__ import annotations

from dataclasses import dataclass

IDENTITY_ATTRS = ("Id", "Name", "UIName", "UIInfo")

GROUP_ORDER = (
    "Combat",
    "Protection",
    "Consumable",
    "Requirements",
    "Durability",
    "Economy",
    "Appearance",
    "Model & Visuals",
    "Other",
)


@dataclass(frozen=True)
class FieldInfo:
    label: str
    group: str
    help: str = ""
    scale: float = 1.0
    unit: str = ""


FIELDS: dict[str, FieldInfo] = {
    "Attack": FieldInfo("Attack", "Combat", "Base damage at full condition."),
    "AttackModStab": FieldInfo("Stab multiplier", "Combat", "Share of Attack applied as stab damage."),
    "AttackModSlash": FieldInfo("Slash multiplier", "Combat", "Share of Attack applied as slash damage."),
    "AttackModSmash": FieldInfo("Blunt multiplier", "Combat", "Share of Attack applied as blunt damage."),
    "AttackStab": FieldInfo("Stab damage", "Combat"),
    "AttackSlash": FieldInfo("Slash damage", "Combat"),
    "AttackSmash": FieldInfo("Blunt damage", "Combat"),
    "Defense": FieldInfo("Parry defense", "Combat", "Defense while blocking with this weapon."),
    "Power": FieldInfo("Draw power", "Combat", "Projectile power of a bow or crossbow."),
    "PowerMod": FieldInfo("Power modifier", "Combat"),
    "LimbResistance": FieldInfo("Limb resistance", "Combat"),
    "Class": FieldInfo("Weapon class", "Combat", "Row in weapon_class.xml, e.g. 4 = longsword."),
    "SubClass": FieldInfo("Weapon subclass", "Combat", "Row in weapon_sub_class.xml."),
    "RpgWeight": FieldInfo("RPG weight", "Combat"),
    "DefenseStab": FieldInfo("Stab defense", "Protection"),
    "DefenseSlash": FieldInfo("Slash defense", "Protection"),
    "DefenseSmash": FieldInfo("Blunt defense", "Protection"),
    "Noise": FieldInfo("Noise", "Protection", "How loud the piece is when moving (0-1)."),
    "VisorTypeId": FieldInfo("Visor type", "Protection"),
    "NumberOfQuickSlots": FieldInfo("Quick slots", "Protection"),
    "HealthBenefit": FieldInfo("Health", "Consumable"),
    "NutritionBenefit": FieldInfo("Nutrition", "Consumable"),
    "RefreshBenefit": FieldInfo("Energy", "Consumable"),
    "AlcoholContent": FieldInfo("Alcohol", "Consumable"),
    "DecayTime": FieldInfo("Decay time", "Consumable", "Hours until the item spoils (0 = never)."),
    "ShortTermNutritionBenefitRatio": FieldInfo("Short-term nutrition ratio", "Consumable"),
    "Efficiency": FieldInfo("Efficiency", "Consumable"),
    "WeaponChargeCount": FieldInfo("Weapon charges", "Consumable"),
    "AmmoApplyCount": FieldInfo("Ammo charges", "Consumable"),
    "BuffDefinitionId": FieldInfo("Buff GUID", "Consumable"),
    "WeaponBuffDefinitionId": FieldInfo("Weapon buff GUID", "Consumable"),
    "IsDivisible": FieldInfo("Stackable", "Consumable"),
    "StrReq": FieldInfo("Strength", "Requirements"),
    "AgiReq": FieldInfo("Agility", "Requirements"),
    "MaxStatus": FieldInfo("Durability", "Durability", "Maximum condition of the item."),
    "MaxQuality": FieldInfo("Max quality", "Durability", "Highest quality tier (1-4)."),
    "IsBreakable": FieldInfo("Can break", "Durability"),
    "BrokenItemClassId": FieldInfo("Broken item GUID", "Durability", "Item that replaces this one when it breaks."),
    "Price": FieldInfo("Price", "Economy", "Shown in groschen; stored in decigroschen.", scale=10.0, unit="gr"),
    "Weight": FieldInfo("Weight", "Economy", unit="kg"),
    "DisplayInShop": FieldInfo("Sold in shops", "Economy"),
    "IsQuestItem": FieldInfo("Quest item", "Economy"),
    "PickpocketInPouch": FieldInfo("Pickpocketable", "Economy"),
    "Charisma": FieldInfo("Charisma", "Appearance"),
    "Visibility": FieldInfo("Visibility", "Appearance"),
    "Conspicuousness": FieldInfo("Conspicuousness", "Appearance"),
    "SocialClassId": FieldInfo("Social class", "Appearance"),
    "WealthLevel": FieldInfo("Wealth level", "Appearance"),
    "RPGBuffWeight": FieldInfo("Buff weight", "Appearance"),
    "VisibilityCoef": FieldInfo("Visibility coefficient", "Appearance"),
    "FadeCoef": FieldInfo("Fade coefficient", "Appearance"),
    "Model": FieldInfo("Model", "Model & Visuals", "CGF path relative to Objects/."),
    "Material": FieldInfo("Material", "Model & Visuals"),
    "Clothing": FieldInfo("Clothing / scabbard", "Model & Visuals"),
    "IconId": FieldInfo("Inventory icon", "Model & Visuals"),
    "UiSound": FieldInfo("Inventory sound", "Model & Visuals"),
    "HolsterModel": FieldInfo("Holster model", "Model & Visuals"),
}

TYPE_LABELS = {
    "MeleeWeapon": "Melee weapon",
    "MissileWeapon": "Ranged weapon",
    "Ammo": "Ammunition",
    "Armor": "Armor & clothing",
    "Helmet": "Helmet",
    "Hood": "Hood & coif",
    "Food": "Food & potion",
    "Herb": "Herb",
    "Ointment": "Ointment & repair kit",
    "Poison": "Poison",
    "CraftingMaterial": "Crafting material",
    "MiscItem": "Miscellaneous",
    "QuickSlotContainer": "Pouch & belt",
    "Document": "Document",
    "NPCTool": "NPC tool",
    "Die": "Die",
    "DiceBadge": "Dice badge",
    "Key": "Key",
    "KeyRing": "Key ring",
    "Money": "Money",
    "PickableItem": "Pickable item",
    "AlchemyBase": "Alchemy base",
    "ItemAlias": "Item alias",
}

# Types offered when creating a new item, in menu order.
CREATABLE_TYPES = (
    "MeleeWeapon", "MissileWeapon", "Ammo", "Armor", "Helmet", "Hood",
    "Food", "Ointment", "Poison", "Herb", "CraftingMaterial", "QuickSlotContainer", "MiscItem",
)

RUNTIME_CATEGORY = {
    "MeleeWeapon": "weapons",
    "MissileWeapon": "weapons",
    "Ammo": "weapons",
    "Armor": "armor",
    "Helmet": "armor",
    "Hood": "armor",
}


def type_label(tag: str) -> str:
    return TYPE_LABELS.get(tag, tag)


def field_info(attr: str) -> FieldInfo:
    return FIELDS.get(attr) or FieldInfo(attr, "Other")


def headline_stats(tag: str) -> tuple[str, ...]:
    if tag == "MeleeWeapon":
        return ("Attack", "Defense", "StrReq", "AgiReq")
    if tag == "MissileWeapon":
        return ("Power", "StrReq", "AgiReq")
    if tag == "Ammo":
        return ("AttackStab", "AttackSlash", "AttackSmash")
    if tag in ("Armor", "Helmet", "Hood"):
        return ("DefenseStab", "DefenseSlash", "DefenseSmash")
    if tag == "Food":
        return ("HealthBenefit", "NutritionBenefit", "RefreshBenefit")
    return ("Price", "Weight")
