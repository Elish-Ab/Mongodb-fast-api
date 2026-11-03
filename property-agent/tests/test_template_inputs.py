"""Expected values come from Pivotal's completed analyses of the same properties."""

from pivotal_engine.sources.kc_assessor_parser import parse_detail_page
from pivotal_engine.template_inputs import Status, kc_record_to_inputs


def by_cell(inputs):
    return {i.cell: i for i in inputs}


def test_seattle_sample_matches_completed_analysis(seattle_detail_html):
    cells = by_cell(kc_record_to_inputs(parse_detail_page(seattle_detail_html)))

    assert cells["B6"].value == 5700
    assert cells["B21"].value == "Seattle"
    assert cells["B39"].value == "Single Family"
    assert [cells[c].value for c in ("B40", "B41", "B42", "B43", "B44", "B45")] == [879, 0, 0, 0, 830, 0]
    assert cells["B50"].value == 1918
    assert cells["B6"].status is Status.RECORD
    assert "Detail.aspx?ParcelNbr=9331800500" in cells["B6"].source


def test_bellevue_sample_matches_completed_analysis(bellevue_detail_html):
    cells = by_cell(kc_record_to_inputs(parse_detail_page(bellevue_detail_html)))

    assert cells["B6"].value == 7337
    assert cells["B21"].value == "Bellevue"
    assert cells["B40"].value == 1220
    assert cells["B50"].value == 1954


def test_unmapped_city_becomes_other_and_is_flagged(seattle_detail_html):
    record = parse_detail_page(seattle_detail_html.replace(">SEATTLE<", ">KENMORE<"))
    cells = by_cell(kc_record_to_inputs(record))
    assert cells["B21"].value == "Other"
    assert cells["B21"].status is Status.RECORD


def test_unknown_present_use_is_left_blank_and_flagged(seattle_detail_html):
    html = seattle_detail_html.replace("Single Family(Res Use/Zone)", "Mobile Home")
    cells = by_cell(kc_record_to_inputs(parse_detail_page(html)))
    assert cells["B39"].value is None
    assert cells["B39"].status is Status.CHECK
    assert "Mobile Home" in cells["B39"].note


def test_later_renovation_year_wins(seattle_detail_html):
    marker = 'Year Renovated</b></font></td><td><font size="3">0<'
    assert marker in seattle_detail_html
    html = seattle_detail_html.replace(marker, marker[:-2] + "2018<")
    cells = by_cell(kc_record_to_inputs(parse_detail_page(html)))
    assert cells["B50"].value == 2018
