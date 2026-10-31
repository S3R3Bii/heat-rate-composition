"""Independently bind exact result values to actual SVG bars, ranges, labels and colors."""

import hashlib, json, math, re
from decimal import Decimal, localcontext
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
S = "{http://www.w3.org/2000/svg}"
read = lambda n: json.loads((ROOT / n).read_bytes())


def points(node):
    path = node.find(".//" + S + "path")
    assert path is not None
    values = [
        float(x)
        for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", path.attrib["d"])
    ]
    assert len(values) % 2 == 0
    return list(zip(values[::2], values[1::2]))


def display(value, places):
    text = format(Decimal(value), f"+.{places}f")
    return text.replace("-0." + "0" * places, "+0." + "0" * places)


def main():
    allcases = read("results/v2/development/cases.json") + read(
        "results/v2/held/cases.json"
    )
    cases = {r["case_id"]: r for r in allcases}
    rr = read("results/v2/development/influence_ranges.json") + read(
        "results/v2/held/influence_ranges.json"
    )
    ranges = {r["case_id"]: r for r in rr}
    primary = [
        r
        for r in allcases
        if r["grain"] == "plant_fuel" and r["cohort"] == "pair_common"
    ]
    allrange = [float(r[f]) for r in primary for f in ["within", "mix"]] + [
        float(v)
        for r in rr
        for f in ["within", "mix"]
        for v in [r["ranges"][f]["minimum"], r["ranges"][f]["maximum"]]
    ]
    bound = math.ceil(max(abs(v) for v in allrange) * 1.12 / 0.2) * 0.2
    maps = read("figures/value_map.json")
    assert set(maps) == {
        "latest_reported_bridge",
        "full_case_sensitivity",
        "plant_influence_ranges",
    }
    values = coordinates = labels = colors = hashes = 0
    with localcontext() as context:
        context.prec = 80
        for name, mapping in maps.items():
            tree = ElementTree.parse(ROOT / "figures" / (name + ".svg"))
            ids = {n.get("id"): n for n in tree.iter() if n.get("id")}
            areas = []
            for i in range(len(mapping["axes"])):
                pp = points(ids["data-area-" + str(i)])
                areas.append(
                    (
                        min(x for x, y in pp),
                        max(x for x, y in pp),
                        min(y for x, y in pp),
                        max(y for x, y in pp),
                    )
                )
            assert (
                len(mapping["items"])
                == {
                    "latest_reported_bridge": 21,
                    "full_case_sensitivity": 72,
                    "plant_influence_ranges": 36,
                }[name]
            )
            for item in mapping["items"]:
                row = cases[item["case_id"]]
                axis = mapping["axes"][item["axes"]]
                xmin, xmax, ymin, ymax = areas[item["axes"]]

                def project(p):
                    x, y = p
                    xl, xr = axis["xlim"]
                    yl, yr = axis["ylim"]
                    assert (
                        min(xl, xr) - 1e-10 <= x <= max(xl, xr) + 1e-10
                        and min(yl, yr) - 1e-10 <= y <= max(yl, yr) + 1e-10
                    )
                    return xmin + (x - xl) / (xr - xl) * (xmax - xmin), ymax - (
                        y - yl
                    ) / (yr - yl) * (ymax - ymin)

                def match(gid, expected):
                    nonlocal coordinates
                    actual = points(ids[gid])
                    assert len(actual) in [len(expected), len(expected) + 1], gid
                    for p, q in zip(actual, expected):
                        target = project(q)
                        for a, b in zip(p, target):
                            assert abs(a - b) <= 3e-5, (gid, a, b)
                            coordinates += 1

                def label(gid, text, position):
                    nonlocal labels, coordinates
                    node = ids[gid]
                    actual = " ".join("".join(node.itertext()).split())
                    assert actual == text, (gid, actual, text)
                    tt = node.find(".//" + S + "text")
                    assert tt is not None
                    target = project(position)
                    for k, v in zip(["x", "y"], target):
                        assert abs(float(tt.attrib[k]) - v) <= 3e-5, (
                            gid,
                            k,
                            tt.attrib[k],
                            v,
                        )
                        coordinates += 1
                    labels += 1

                if item["kind"] in ["bar", "connector"]:
                    a = item["axes"]
                    assert (
                        row["end_year"] == 2024
                        and row["fleet"] == ["coal", "natural_gas", "pooled"][a]
                        and row["grain"] == "plant_fuel"
                        and row["cohort"] == "pair_common"
                    )
                    assert axis == dict(xlim=[-0.55, 3.55], ylim=[-0.09, 0.075])
                    fields = [
                        "within",
                        "mix",
                        "outside_cohort_composition_remainder",
                        "full_change",
                    ]
                    if item["kind"] == "bar":
                        i = item["x"]
                        value = Decimal(row[fields[i]])
                        start = (
                            Decimal(0)
                            if i == 3
                            else sum((Decimal(row[f]) for f in fields[:i]), Decimal(0))
                        )
                        end = start + value
                        assert (
                            item["field"] == fields[i]
                            and Decimal(item["value"]) == value
                            and Decimal(item["start"]) == start
                            and Decimal(item["end"]) == end
                        )
                        values += 3
                        match(
                            item["id"],
                            [
                                (i - 0.31, float(start)),
                                (i + 0.31, float(start)),
                                (i + 0.31, float(end)),
                                (i - 0.31, float(end)),
                            ],
                        )
                        padding = (
                            (Decimal(".013") if value >= 0 else Decimal("-.014"))
                            if i == 2
                            else Decimal(".004") if value >= 0 else Decimal("-.008")
                        )
                        ly = end + padding
                        assert Decimal(item["label_y"]) == ly and item[
                            "label"
                        ] == display(value, 4)
                        label(item["id"] + "-label", display(value, 4), (i, float(ly)))
                    else:
                        i = item["after"]
                        value = sum(
                            (Decimal(row[f]) for f in fields[: i + 1]), Decimal(0)
                        )
                        assert Decimal(item["value"]) == value
                        values += 1
                        match(
                            item["id"],
                            [(i + 0.31, float(value)), (i + 1 - 0.31, float(value))],
                        )
                elif item["kind"] == "cell":
                    a = item["axes"]
                    i, j = item["y"], item["x"]
                    method = [
                        ("plant_fuel", "pair_common"),
                        ("plant_fuel", "balanced_2018_2024"),
                        ("plant_technology_fuel", "pair_common"),
                        ("plant_technology_fuel", "balanced_2018_2024"),
                    ][i]
                    assert (
                        row["fleet"] == ["coal", "natural_gas", "pooled"][a]
                        and row["end_year"] == 2019 + j
                        and (row["grain"], row["cohort"]) == method
                    )
                    assert axis == dict(xlim=[-0.5, 5.5], ylim=[3.5, -0.5])
                    assert item["within"] == row["within"] and item["mix"] == row["mix"]
                    values += 2
                    match(
                        item["id"],
                        [
                            (j - 0.5, i - 0.5),
                            (j + 0.5, i - 0.5),
                            (j + 0.5, i + 0.5),
                            (j - 0.5, i + 0.5),
                        ],
                    )
                    value = Decimal(row["within"])
                    base = (249, 249, 247)
                    end = (146, 185, 204) if value >= 0 else (210, 151, 145)
                    fraction = min(abs(float(value)), 1)
                    color = "#" + "".join(
                        f"{round(a+(b-a)*fraction):02x}" for a, b in zip(base, end)
                    )
                    assert (
                        item["color"] == color
                        and "fill: " + color
                        in ids[item["id"]].find(".//" + S + "path").attrib["style"]
                    )
                    colors += 1
                    for f, offset, prefix in [
                        ("within", -0.05, "W"),
                        ("mix", 0.30, "M"),
                    ]:
                        text = prefix + display(row[f], 2)
                        assert item[f + "_label"] == text
                        label(item["id"] + "-" + f, text, (j, i + offset))
                else:
                    assert item["kind"] == "range"
                    i = item["y"]
                    field = ["within", "mix"][item["axes"]]
                    assert (
                        primary[i]["case_id"] == item["case_id"]
                        and item["field"] == field
                    )
                    source = ranges[item["case_id"]]["ranges"][field]
                    assert (
                        item["minimum"] == source["minimum"]
                        and item["maximum"] == source["maximum"]
                        and item["value"] == row[field]
                    )
                    values += 3
                    assert axis == dict(xlim=[-bound, bound], ylim=[17.6, -0.6])
                    match(
                        item["id"],
                        [(float(source["minimum"]), i), (float(source["maximum"]), i)],
                    )
                    use = ids[item["id"] + "-point"].find(".//" + S + "use")
                    assert use is not None
                    target = project((float(row[field]), i))
                    for k, v in zip(["x", "y"], target):
                        assert abs(float(use.attrib[k]) - v) <= 3e-5
                        coordinates += 1
            for ext, digest in mapping["sha256"].items():
                assert (
                    hashlib.sha256(
                        (ROOT / "figures" / (name + "." + ext)).read_bytes()
                    ).hexdigest()
                    == digest
                )
                hashes += 1
            assert (ROOT / "paper/images" / (name + ".pdf")).read_bytes() == (
                ROOT / "figures" / (name + ".pdf")
            ).read_bytes()
    result = dict(
        status="PASS_SOURCE_BOUND_VALUES_AND_ACTUAL_SVG",
        figures=3,
        mapped_source_values_and_positions=values,
        svg_coordinates=coordinates,
        individual_numeric_labels=labels,
        source_bound_cell_colors=colors,
        file_hashes=hashes,
        coverage="Latest three-fleet bridge; all72 within/mix case cells; both components for all18 primary finite plant-influence ranges",
        limitation="Specific source/value/geometry/color/label checks plus separate visual review; no universal correctness or accessibility-conformance claim.",
    )
    (ROOT / "figures/verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
