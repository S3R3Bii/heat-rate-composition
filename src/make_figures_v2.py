"""Render reported-ratio components, all case sensitivities and finite plant influence."""

import hashlib, json, math, platform, shutil
from decimal import Decimal, localcontext
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "svg.fonttype": "none",
        "svg.hashsalt": "heat25-v2",
        "path.simplify": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "text.color": "#203d4b",
        "axes.labelcolor": "#203d4b",
    }
)
read = lambda n: json.loads((ROOT / n).read_bytes())
ALL = read("results/v2/development/cases.json") + read("results/v2/held/cases.json")
RANGES = read("results/v2/development/influence_ranges.json") + read(
    "results/v2/held/influence_ranges.json"
)
MAP = {}


def signed(value, places):
    text = format(Decimal(value), f"+.{places}f")
    return text.replace("-0." + "0" * places, "+0." + "0" * places)


def save(fig, name, items):
    folder = ROOT / "figures"
    folder.mkdir(exist_ok=True)
    images = ROOT / "paper/images"
    images.mkdir(parents=True, exist_ok=True)
    for i, ax in enumerate(fig.axes):
        ax.patch.set_gid("data-area-" + str(i))
    fig.savefig(folder / (name + ".svg"), metadata={"Date": None})
    path = folder / (name + ".svg")
    path.write_bytes(
        (
            "\n".join(
                line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()
            )
            + "\n"
        ).encode()
    )
    fig.savefig(
        folder / (name + ".pdf"), metadata={"CreationDate": None, "ModDate": None}
    )
    fig.savefig(folder / (name + ".png"), dpi=150)
    shutil.copyfile(folder / (name + ".pdf"), images / (name + ".pdf"))
    MAP[name] = dict(
        axes=[
            dict(xlim=list(ax.get_xlim()), ylim=list(ax.get_ylim())) for ax in fig.axes
        ],
        items=items,
        sha256={
            ext: hashlib.sha256((folder / (name + "." + ext)).read_bytes()).hexdigest()
            for ext in ["svg", "pdf", "png"]
        },
    )
    plt.close(fig)


def latest():
    fig, aa = plt.subplots(1, 3, figsize=(8.8, 4.9))
    fig.subplots_adjust(left=0.09, right=0.98, top=0.72, bottom=0.25, wspace=0.42)
    fig.text(
        0.09,
        0.96,
        "A small ratio change can hide opposing terms",
        fontsize=15,
        weight="bold",
    )
    fig.text(
        0.09,
        0.87,
        "2023–2024; unambiguous non-CHP reporting cohort. Units: MMBtu/MWh.",
        fontsize=9,
    )
    items = []
    for a, fleet in enumerate(["coal", "natural_gas", "pooled"]):
        ax = aa[a]
        row = next(
            r
            for r in ALL
            if r["end_year"] == 2024
            and r["fleet"] == fleet
            and r["grain"] == "plant_fuel"
            and r["cohort"] == "pair_common"
        )
        current = Decimal(0)
        for i, (field, color) in enumerate(
            [
                ("within", "#24627b"),
                ("mix", "#b8762f"),
                ("outside_cohort_composition_remainder", "#8b9398"),
                ("full_change", "#203d4b"),
            ]
        ):
            value = Decimal(row[field])
            start = Decimal(0) if i == 3 else current
            end = start + value
            gid = f"latest-{a}-{i}"
            ax.bar([i], [float(value)], bottom=[float(start)], width=0.62, color=color)[
                0
            ].set_gid(gid)
            label_y = end + (
                (Decimal(".013") if value >= 0 else Decimal("-.014"))
                if i == 2
                else (Decimal(".004") if value >= 0 else Decimal("-.008"))
            )
            ax.text(
                i,
                float(label_y),
                signed(value, 4),
                ha="center",
                va="baseline",
                fontsize=9,
            ).set_gid(gid + "-label")
            items.append(
                dict(
                    id=gid,
                    kind="bar",
                    axes=a,
                    case_id=row["case_id"],
                    field=field,
                    value=row[field],
                    x=i,
                    start=str(start),
                    end=str(end),
                    label=signed(value, 4),
                    label_y=str(label_y),
                )
            )
            if i < 3:
                lineid = gid + "-connector"
                ax.plot(
                    [i + 0.31, i + 1 - 0.31],
                    [float(end)] * 2,
                    color="#647b86",
                    linewidth=0.7,
                )[0].set_gid(lineid)
                items.append(
                    dict(
                        id=lineid,
                        kind="connector",
                        axes=a,
                        case_id=row["case_id"],
                        after=i,
                        value=str(end),
                    )
                )
            current = end
        ax.set_title(
            {"coal": "Coal", "natural_gas": "Natural gas", "pooled": "Pooled"}[fleet]
        )
        ax.set_xlim(-0.55, 3.55)
        ax.set_ylim(-0.09, 0.075)
        ax.set_xticks(
            range(4), ["Within", "Mix", "Outside\ncohort", "Total"], fontsize=8
        )
        ax.axhline(0, color="#526b78", linewidth=0.8)
        ax.grid(axis="y", alpha=0.15)
        ax.set_axisbelow(True)
        if a == 0:
            ax.set_ylabel("Change in reported ratio (MMBtu/MWh)")
    fig.text(
        0.09,
        0.12,
        "Labels: component changes; the final bar is their total. The outside term includes eligibility/matching.",
        fontsize=8,
    )
    fig.text(
        0.09,
        0.06,
        "These are algebraic reported-data components, not physical efficiency or causal effects.",
        fontsize=8,
    )
    save(fig, "latest_reported_bridge", items)


def cell_color(value):
    base = (249, 249, 247)
    end = (146, 185, 204) if value >= 0 else (210, 151, 145)
    f = min(abs(float(value)), 1)
    return "#" + "".join(f"{round(a+(b-a)*f):02x}" for a, b in zip(base, end))


def sensitivity():
    fig, aa = plt.subplots(3, 1, figsize=(8.8, 8.1))
    fig.subplots_adjust(left=0.25, right=0.98, top=0.83, bottom=0.17, hspace=0.58)
    fig.text(
        0.10,
        0.96,
        "Within and mix depend on grain and cohort",
        fontsize=15,
        weight="bold",
    )
    fig.text(
        0.10,
        0.91,
        "Every fixed case. W: within; M: mix. Units: MMBtu/MWh; labels rounded to two decimals.",
        fontsize=9,
    )
    methods = [
        ("plant_fuel", "pair_common"),
        ("plant_fuel", "balanced_2018_2024"),
        ("plant_technology_fuel", "pair_common"),
        ("plant_technology_fuel", "balanced_2018_2024"),
    ]
    items = []
    for a, fleet in enumerate(["coal", "natural_gas", "pooled"]):
        ax = aa[a]
        for i, (grain, cohort) in enumerate(methods):
            for j, end in enumerate(range(2019, 2025)):
                row = next(
                    r
                    for r in ALL
                    if r["end_year"] == end
                    and r["fleet"] == fleet
                    and r["grain"] == grain
                    and r["cohort"] == cohort
                )
                gid = f"sensitivity-{a}-{i}-{j}"
                value = Decimal(row["within"])
                color = cell_color(value)
                ax.add_patch(
                    Rectangle(
                        (j - 0.5, i - 0.5),
                        1,
                        1,
                        facecolor=color,
                        edgecolor="white",
                        linewidth=1,
                        gid=gid,
                    )
                )
                for field, offset, prefix in [
                    ("within", -0.05, "W"),
                    ("mix", 0.30, "M"),
                ]:
                    ax.text(
                        j,
                        i + offset,
                        prefix + signed(row[field], 2),
                        ha="center",
                        va="baseline",
                        fontsize=7.5,
                        color="#162e3b",
                    ).set_gid(gid + "-" + field)
                items.append(
                    dict(
                        id=gid,
                        kind="cell",
                        axes=a,
                        case_id=row["case_id"],
                        x=j,
                        y=i,
                        within=row["within"],
                        mix=row["mix"],
                        color=color,
                        within_label="W" + signed(row["within"], 2),
                        mix_label="M" + signed(row["mix"], 2),
                    )
                )
        ax.set_xlim(-0.5, 5.5)
        ax.set_ylim(3.5, -0.5)
        ax.set_xticks(
            range(6), [f"{y-1}–{str(y)[-2:]}" for y in range(2019, 2025)], fontsize=8
        )
        ax.set_yticks(
            range(4),
            [
                "Plant/fuel · pair",
                "Plant/fuel · balanced",
                "Plant/tech/fuel · pair",
                "Plant/tech/fuel · balanced",
            ],
            fontsize=8,
        )
        ax.tick_params(length=0)
        ax.set_title(
            {"coal": "Coal", "natural_gas": "Natural gas", "pooled": "Pooled"}[fleet],
            loc="left",
            fontsize=11,
            weight="bold",
        )
    fig.text(
        0.10,
        0.10,
        "Colour shows within on a fixed −1 to +1 scale: pale red (negative), white (zero), pale blue (positive).",
        fontsize=8,
    )
    fig.text(
        0.10,
        0.06,
        "Balanced eligibility uses all seven years. Different matching/aggregation does not identify causality.",
        fontsize=8,
    )
    save(fig, "full_case_sensitivity", items)


def influence():
    primary = [
        r for r in ALL if r["grain"] == "plant_fuel" and r["cohort"] == "pair_common"
    ]
    lookup = {r["case_id"]: r for r in RANGES}
    all_values = [float(r[field]) for r in primary for field in ["within", "mix"]] + [
        float(v)
        for r in RANGES
        for field in ["within", "mix"]
        for v in [r["ranges"][field]["minimum"], r["ranges"][field]["maximum"]]
    ]
    bound = math.ceil(max(abs(v) for v in all_values) * 1.12 / 0.2) * 0.2
    fig, aa = plt.subplots(1, 2, figsize=(8.8, 7.8))
    fig.subplots_adjust(left=0.23, right=0.97, top=0.82, bottom=0.19, wspace=0.23)
    fig.text(0.23, 0.96, "Plant influence remains visible", fontsize=15, weight="bold")
    fig.text(
        0.23,
        0.90,
        "All primary pairs/fleets; delete every matched fuel cell of one plant.",
        fontsize=9,
    )
    items = []
    labels = [
        f"{r['start_year']}–{str(r['end_year'])[-2:]} "
        + {"coal": "coal", "natural_gas": "gas", "pooled": "pooled"}[r["fleet"]]
        for r in primary
    ]
    for a, field in enumerate(["within", "mix"]):
        ax = aa[a]
        for i, row in enumerate(primary):
            rr = lookup[row["case_id"]]["ranges"][field]
            lo, hi = rr["minimum"], rr["maximum"]
            value = row[field]
            gid = f"influence-{a}-{i}"
            ax.plot([float(lo), float(hi)], [i, i], color="#8b9398", linewidth=2)[
                0
            ].set_gid(gid)
            ax.plot([float(value)], [i], marker="o", markersize=4, color="#24627b")[
                0
            ].set_gid(gid + "-point")
            items.append(
                dict(
                    id=gid,
                    kind="range",
                    axes=a,
                    case_id=row["case_id"],
                    field=field,
                    y=i,
                    minimum=lo,
                    maximum=hi,
                    value=value,
                )
            )
        ax.set_xlim(-bound, bound)
        ax.set_ylim(17.6, -0.6)
        ax.set_yticks(range(18), labels if a == 0 else [""] * 18, fontsize=8)
        ax.set_title(field.title())
        ax.set_xlabel("MMBtu/MWh")
        ax.axvline(0, color="#526b78", linewidth=0.7, linestyle="--")
        ax.grid(axis="x", alpha=0.12)
        ax.set_axisbelow(True)
    fig.text(
        0.23,
        0.095,
        "Dot: full matched cohort. Line: minimum/maximum over the finite plant deletions.",
        fontsize=8,
    )
    fig.text(
        0.23,
        0.055,
        "These ranges are influence checks, not confidence intervals or future uncertainty bounds.",
        fontsize=8,
    )
    save(fig, "plant_influence_ranges", items)


if __name__ == "__main__":
    with localcontext() as context:
        context.prec = 80
        latest()
        sensitivity()
        influence()
    (ROOT / "figures/value_map.json").write_bytes(
        (json.dumps(MAP, indent=2) + "\n").encode()
    )
    (ROOT / "figures/render_runtime.json").write_bytes(
        (
            json.dumps(
                dict(
                    python=platform.python_version(),
                    matplotlib=matplotlib.__version__,
                    font="DejaVu Sans",
                ),
                indent=2,
            )
            + "\n"
        ).encode()
    )
    print(
        "Rendered three reported-data figures; independent source/geometry checks and inspection pending."
    )
