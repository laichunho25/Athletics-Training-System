"""運動練習項目庫。

項目庫是全站唯一的「有哪些動作可以練」的來源：
課表挑得到的動作、數據分析追蹤得到的項目，都從這裡出。

分四層看：

    運動種類（田徑）→ 運動項目（短跑）→ 訓練動作種類（專項動作）→ 動作

三層目錄與動作本身都可以由教練／運動員／管理員新增，但新加的先是
「待管理員確認」，確認之後才會永久出現在項目庫與別人的挑選清單裡。
"""

import io

from django.core.management import call_command
from django.db.models import Q

from core.models import Role
from training.models import (
    ActivityDefinition,
    Discipline,
    LibraryStatus,
    MovementKind,
    SportType,
)


def ensure_activity_library():
    """項目庫缺東西就載入預設清單；回傳目前的動作數。

    動作與目錄兩邊都要檢查：升級到分層目錄之前建的資料庫有一堆動作、
    卻一個運動種類都沒有，只看動作數會以為不用補。
    """
    if ActivityDefinition.objects.exists() and SportType.objects.exists():
        return ActivityDefinition.objects.count()
    # 種子指令會印一行結果，這裡是背景補資料，不用吵到畫面／測試輸出
    call_command("seed_activities", verbosity=0, stdout=io.StringIO())
    return ActivityDefinition.objects.count()


def is_library_admin(user):
    """只有管理員能確認別人加進來的東西。"""
    return bool(user and user.is_authenticated and user.role == Role.ADMIN)


def visible_filter(user):
    """挑選清單看得到什麼：已確認的大家都看得到，待確認的只有本人與管理員。

    「等管理員確認才可以永久在項目庫出現」——所以別人看不到；
    但自己剛加的東西如果連自己都挑不到，加了也沒用，所以留給本人。
    """
    approved = Q(status=LibraryStatus.APPROVED)
    if is_library_admin(user):
        return approved | Q(status=LibraryStatus.PENDING)
    if user is not None and user.is_authenticated:
        return approved | Q(status=LibraryStatus.PENDING, created_by=user)
    return approved


def visible_definitions(user):
    """課表與數據分析的挑選清單：可挑選、且看得到的動作。"""
    return (
        ActivityDefinition.objects.filter(visible_filter(user), is_active=True)
        .select_related("discipline__sport", "movement_kind")
        .prefetch_related("extra_disciplines__sport")
        .order_by("discipline__sport__order", "discipline__order", "category",
                  "-use_count", "name")
    )


def definition_disciplines(definition):
    """一個動作掛在哪些運動項目底下（主項目排前面）。

    同一個動作常常好幾種運動都在練——深蹲在田徑也在體能訓練——所以
    項目庫允許把它加進別的運動種類，挑選清單每一個都要出現。
    """
    return definition.all_disciplines


def library_groups(definitions):
    """把動作依「運動種類 · 運動項目」分組，給下拉選單的 optgroup 用。

    還沒歸到運動項目的動作（例如舊資料）退回用分類的名稱分組，
    這樣升級到分層目錄之前寫進去的東西也不會從清單上消失。
    """
    from training.models import ActivityCategory

    labels = dict(ActivityCategory.choices)
    groups = {}
    for d in definitions:
        homes = definition_disciplines(d)
        if not homes:
            key = ("c", d.category)
            label = labels.get(d.category, "其他")
            groups.setdefault(
                key,
                {"value": key[1], "label": label, "sort": (1, 0, "", 0, label), "rows": []},
            )["rows"].append(d)
            continue
        for disc in homes:
            key = ("d", disc.id)
            groups.setdefault(
                key,
                {
                    "value": disc.id,
                    "label": disc.full_label,
                    "sort": (0, disc.sport.order, disc.sport.name, disc.order, disc.name),
                    "rows": [],
                },
            )["rows"].append(d)
    return sorted(groups.values(), key=lambda g: g["sort"])


def library_tree(user, sport=None, discipline=None):
    """項目庫頁面的資料：運動種類 → 運動項目 → 訓練動作種類 → 動作。

    ``sport`` / ``discipline`` 有給就只展開那一支，其餘只回標題，
    否則一頁要印一百多個動作，找東西反而更慢。
    """
    where = visible_filter(user)
    sports = list(SportType.objects.filter(where).order_by("order", "name"))
    disciplines = list(
        Discipline.objects.filter(where).select_related("sport").order_by(
            "sport__order", "order", "name"
        )
    )
    kinds = list(MovementKind.objects.filter(where).order_by("order", "name"))

    library = list(visible_definitions(user))
    counts = {}
    for d in library:
        for disc in definition_disciplines(d):
            counts[disc.id] = counts.get(disc.id, 0) + 1

    by_sport = {}
    for disc in disciplines:
        by_sport.setdefault(disc.sport_id, []).append(
            {"obj": disc, "count": counts.get(disc.id, 0)}
        )

    tree = [
        {
            "obj": s,
            "disciplines": by_sport.get(s.id, []),
            "count": sum(d["count"] for d in by_sport.get(s.id, [])),
            "open": sport is not None and s.id == sport.id,
        }
        for s in sports
    ]

    rows = []
    if discipline is not None:
        picked = [
            d
            for d in library
            if discipline.id in {disc.id for disc in definition_disciplines(d)}
        ]
        by_kind = {}
        for d in picked:
            by_kind.setdefault(d.movement_kind_id, []).append(d)
        for kind in kinds:
            if by_kind.get(kind.id):
                rows.append({"kind": kind, "rows": by_kind[kind.id]})
        if by_kind.get(None):
            rows.append({"kind": None, "rows": by_kind[None]})

    return {"sports": tree, "kinds": kinds, "disciplines": disciplines, "blocks": rows}


def pending_submissions(user):
    """待確認的東西：管理員看全部，其他人看自己加的。"""
    where = Q(status=LibraryStatus.PENDING)
    if not is_library_admin(user):
        where &= Q(created_by=user)
    return {
        "sports": list(SportType.objects.filter(where).order_by("name")),
        "disciplines": list(
            Discipline.objects.filter(where).select_related("sport").order_by("name")
        ),
        "kinds": list(MovementKind.objects.filter(where).order_by("name")),
        "activities": list(
            ActivityDefinition.objects.filter(where)
            .select_related("discipline__sport", "movement_kind")
            .order_by("name")
        ),
    }


def library_catalog(user, definitions=None):
    """兩欄連動挑選用的資料：運動種類 → 運動項目 → 動作。

    課表、本課數據紀錄、數據分析三處都是「先挑田徑、再挑短跑，相關的動作
    才列出來」，共用這一份 JSON，前端只要照 sport → discipline 往下走。
    """
    from training.models import ActivityCategory

    labels = dict(ActivityCategory.choices)
    rows = list(visible_definitions(user)) if definitions is None else list(definitions)
    sports = {}

    def bucket(sport_key, sport_name, sport_order, disc_key, disc_name, disc_order):
        sport = sports.setdefault(
            sport_key,
            {"id": sport_key, "name": sport_name, "order": sport_order, "disciplines": {}},
        )
        return sport["disciplines"].setdefault(
            disc_key,
            {"id": disc_key, "name": disc_name, "order": disc_order, "activities": []},
        )

    for d in rows:
        entry = {"id": d.id, "name": d.name, "name_en": d.name_en, "note": d.note}
        homes = definition_disciplines(d)
        if not homes:
            # 還沒歸到運動項目的舊資料，用分類名稱擺在「其他」底下，免得挑不到
            bucket("other", "其他", 999, f"c{d.category}",
                   labels.get(d.category, "其他"), 999)["activities"].append(entry)
            continue
        for disc in homes:
            bucket(disc.sport_id, disc.sport.name, disc.sport.order,
                   disc.id, disc.name, disc.order)["activities"].append(entry)

    out = []
    for sport in sorted(sports.values(), key=lambda s: (s["order"], str(s["name"]))):
        out.append(
            {
                "id": sport["id"],
                "name": sport["name"],
                "disciplines": [
                    {"id": d["id"], "name": d["name"], "activities": d["activities"]}
                    for d in sorted(
                        sport["disciplines"].values(),
                        key=lambda d: (d["order"], str(d["name"])),
                    )
                ],
            }
        )
    return out
