from fastapi import APIRouter, HTTPException, Query

import cairn.srd as srd

router = APIRouter(prefix="/v1/srd", tags=["srd"])


@router.get("/races")
def list_races() -> list[dict]:
    return srd.list_races()


@router.get("/races/{index}")
def get_race(index: str) -> dict:
    race = srd.get_race(index)
    if race is None:
        raise HTTPException(status_code=404, detail="Race not found")
    race["subraces"] = [s for s in srd.list_subraces() if s.get("race", {}).get("index") == index]
    return race


@router.get("/subraces")
def list_subraces() -> list[dict]:
    return srd.list_subraces()


@router.get("/subraces/{index}")
def get_subrace(index: str) -> dict:
    subrace = srd.get_subrace(index)
    if subrace is None:
        raise HTTPException(status_code=404, detail="Subrace not found")
    return subrace


@router.get("/classes")
def list_classes() -> list[dict]:
    return srd.list_classes()


@router.get("/classes/{index}")
def get_class(index: str, level: int = Query(default=1, ge=1, le=20)) -> dict:
    cls = srd.get_class(index)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    levels = srd.get_class_levels(index)
    cls["levels"] = [lvl for lvl in levels if lvl.get("level", 0) <= level]
    return cls


@router.get("/backgrounds")
def list_backgrounds() -> list[dict]:
    return srd.list_backgrounds()


@router.get("/backgrounds/{index}")
def get_background(index: str) -> dict:
    bg = srd.get_background(index)
    if bg is None:
        raise HTTPException(status_code=404, detail="Background not found")
    return bg


@router.get("/feats")
def list_feats() -> list[dict]:
    return srd.list_all_feats()


@router.get("/feats/{index}")
def get_feat(index: str) -> dict:
    feat = srd.get_feat(index)
    if feat is None:
        raise HTTPException(status_code=404, detail="Feat not found")
    return feat


@router.get("/spells")
def list_spells(
    class_index: str | None = Query(default=None),
    max_level: int | None = Query(default=None, ge=0, le=9),
) -> list[dict]:
    return srd.list_spells(class_index=class_index, max_level=max_level)


@router.get("/spells/{index}")
def get_spell(index: str) -> dict:
    spell = srd.get_spell(index)
    if spell is None:
        raise HTTPException(status_code=404, detail="Spell not found")
    return spell


@router.get("/equipment")
def list_equipment(category: str | None = Query(default=None)) -> list[dict]:
    return srd.list_equipment(category=category)


@router.get("/conditions")
def list_conditions() -> list[dict]:
    return srd.get_all_conditions()


@router.get("/conditions/{name}")
def get_condition(name: str) -> dict:
    condition = srd.get_condition(name)
    if condition is None:
        raise HTTPException(status_code=404, detail="Condition not found")
    return condition


@router.get("/monsters")
def list_monsters(max_cr: float | None = Query(default=None)) -> list[dict]:
    return srd.list_monsters(max_cr=max_cr)


@router.get("/skills")
def list_skills() -> list[dict]:
    return srd.list_skills()


@router.get("/languages")
def list_languages() -> list[dict]:
    return srd.list_languages()
