"""Deduplication accuracy vs ground truth; PPRL helpers; code/unit mapping.

Synthetic data — for demonstration only.
"""

from exchange.normalize import CodeMap
from labcore import codes as C
from labcore.pprl import soundex, standardize_family, standardize_given, tokens


def test_dedup_accuracy_vs_ground_truth(sim):
    d = sim["exchange"]["dedup"]
    assert d["precision"] >= 0.98
    assert d["recall"] >= 0.85
    # linkage gets much closer to the true person count than no deduplication
    assert abs(d["predicted_persons"] - d["true_persons"]) < 0.25 * (d["records"] - d["true_persons"])


def test_pprl_helpers():
    assert soundex("Robert") == soundex("Rupert") == "R163"
    assert soundex("Tymczak") == "T522"
    assert standardize_given("Bill") == "WILLIAM"
    assert standardize_family("Garcia-Lopez") == "GARCIA"
    a = tokens("William", "Smith", "1960-05-04", "male", "00101")
    b = tokens("Bill", "Smith", "1960-05-04", "male", "00101")
    assert a["T1"] == b["T1"]
    c = tokens("William", "Smiht", "1960-05-04", "male", "00101")
    assert c["T1"] != a["T1"] and c["T5"] == a["T5"]


def test_ifcc_to_ngsp_conversion():
    assert C.ifcc_to_ngsp(48) == 6.5  # 48 mmol/mol ~ 6.5 % (NGSP master equation)
    assert C.ifcc_to_ngsp(75) == 9.0
    assert C.ngsp_to_ifcc(6.5) == 48


def test_code_map_covers_all_local_codes():
    cm = CodeMap.load()
    for code in C.LOCAL_DX_CODES:
        assert (C.LOCAL_DX_RHC, code) in cm.codes
    assert (C.LOCAL_LAB_FQHC, "A1C-IFCC") in cm.codes
    assert set(cm.med_text.values()) == set(C.MED_FREE_TEXT)
    assert cm.units["mmHg"] == "mm[Hg]"


def test_mapping_changes_what_is_recognized(sim):
    m, u = sim["exchange"]["normalization_mapped"], sim["exchange"]["normalization_unmapped"]
    assert m["conditions_mapped_from_local"] > 0
    assert u.get("conditions_unrecognized", 0) >= m["conditions_mapped_from_local"]
    assert m["a1c_converted_ifcc"] > 0 and m["meds_mapped_from_text"] > 0
    assert u.get("bp_unit_unrecognized", 0) > 0 and m.get("bp_unit_unrecognized", 0) == 0
