from datetime import datetime
from pathlib import Path

import pytest
from lxml import etree

from logixconfig.l5x import build_l5x, build_tag_element
from logixconfig.models import DataType, Tag

GOLDEN_TAGS = Path(__file__).parent / "golden" / "tags.xml"
EXPORT_DATE = datetime(2026, 11, 2, 14, 30, 0)
EXPORT_DATE_TEXT = "Mon Nov 02 14:30:00 2026"

CONTROLLER_CHILD_ORDER = [
    "RedundancyInfo",
    "Security",
    "SafetyInfo",
    "DataTypes",
    "Modules",
    "AddOnInstructionDefinitions",
    "Tags",
    "Programs",
    "Tasks",
    "CST",
    "WallClockTime",
    "Trends",
    "DataLogs",
    "TimeSynchronize",
]

BOOLEAN_ATTRIBUTES = {
    "ContainsContext",
    "MatchProjectToController",
    "CanUseRPIFromProducer",
    "DownloadProjectDocumentationAndExtendedProperties",
    "Enabled",
    "KeepTestEditsOnSwitchOver",
    "Inhibited",
    "MajorFault",
    "Upstream",
    "Constant",
    "TestEdits",
    "Disabled",
    "UseAsFolder",
    "DisableUpdateOutputs",
    "InhibitTask",
    "PTPEnable",
}


def make_tag(name: str = "P101_Run_Cmd", data_type: str = "BOOL", description: str = "Run command") -> Tag:
    return Tag(name=name, data_type=data_type, description=description, equipment="P101")


def build(tags: list[Tag], **options) -> bytes:
    return build_l5x(tags, "Skid01", export_date=EXPORT_DATE, **options)


def parse(xml: bytes) -> etree._Element:
    return etree.fromstring(xml)


def structure(element: etree._Element) -> tuple:
    text = (element.text or "").strip()
    return (element.tag, list(element.attrib.items()), text, [structure(child) for child in element])


def golden_tags() -> list[etree._Element]:
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True)
    return list(etree.parse(str(GOLDEN_TAGS), parser).getroot())


def tag_from_golden(element: etree._Element) -> Tag:
    description = element.find("Description")
    return make_tag(
        name=element.get("Name"),
        data_type=element.get("DataType"),
        description=description.text if description is not None else "",
    )


# Tag elements


def test_golden_covers_every_data_type() -> None:
    assert sorted(element.get("DataType") for element in golden_tags()) == sorted(t.value for t in DataType)


@pytest.mark.parametrize("golden", golden_tags(), ids=lambda element: element.get("DataType"))
def test_tag_element_matches_golden(golden: etree._Element) -> None:
    generated = build_tag_element(tag_from_golden(golden))
    assert structure(generated) == structure(golden)


def test_real_tag_encoding() -> None:
    element = build_tag_element(make_tag("LT101_PV", "REAL"))
    raw, decorated = element.findall("Data")
    value = decorated.find("DataValue")
    assert element.get("Radix") == "Float"
    assert raw.text == "00 00 00 00"
    assert (value.get("DataType"), value.get("Radix"), value.get("Value")) == ("REAL", "Float", "0.0")


def test_description_comes_before_data() -> None:
    children = [child.tag for child in build_tag_element(make_tag())]
    assert children == ["Description", "Data", "Data"]


def test_raw_data_comes_before_decorated() -> None:
    raw, decorated = build_tag_element(make_tag()).findall("Data")
    assert raw.get("Format") is None
    assert decorated.get("Format") == "Decorated"


def test_no_safety_or_opc_attributes_on_tags() -> None:
    element = build_tag_element(make_tag())
    assert element.get("Class") is None
    assert element.get("OpcUaAccess") is None


def test_description_is_written_as_cdata() -> None:
    assert b"<Description><![CDATA[Run command]]></Description>" in build([make_tag()])


def test_empty_description_omits_description_element() -> None:
    assert build_tag_element(make_tag(description="")).find("Description") is None


def test_include_descriptions_false_omits_description_element() -> None:
    root = parse(build([make_tag()], include_descriptions=False))
    assert root.find("Controller/Tags/Tag/Description") is None


def test_description_special_characters_round_trip() -> None:
    text = 'Tank <TK-100> level & "pressure"'
    root = parse(build([make_tag(description=text)]))
    assert root.find("Controller/Tags/Tag/Description").text == text


def test_description_containing_cdata_end_marker_is_well_formed() -> None:
    root = parse(build([make_tag(description="odd ]]> text")]))
    assert root.find("Controller/Tags/Tag/Description").text == "odd ]]> text"


def test_description_with_control_character_raises() -> None:
    with pytest.raises(ValueError, match="P101_Run_Cmd"):
        build([make_tag(description="bad \x07 text")])


# Document and skeleton


def test_xml_declaration_uses_double_quotes() -> None:
    assert build([]).startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<RSLogix5000Content')


def test_controller_child_order_matches_sample_export() -> None:
    controller = parse(build([make_tag()])).find("Controller")
    assert [child.tag for child in controller] == CONTROLLER_CHILD_ORDER


def test_content_header() -> None:
    root = parse(build([]))
    assert root.get("SoftwareRevision") == "24.02"
    assert root.get("TargetName") == "Skid01"
    assert root.get("TargetType") == "Controller"
    assert root.get("Owner") == "logixconfig-ai"
    assert root.get("ExportDate") == EXPORT_DATE_TEXT


def test_controller_attributes() -> None:
    controller = parse(build([])).find("Controller")
    assert controller.get("Name") == "Skid01"
    assert controller.get("ProcessorType") == "1756-L71"
    assert (controller.get("MajorRev"), controller.get("MinorRev")) == ("24", "11")
    assert controller.get("ProjectCreationDate") == EXPORT_DATE_TEXT
    assert controller.get("LastModifiedDate") == EXPORT_DATE_TEXT
    assert controller.get("ProjectSN") == "16#0000_0000"


def test_local_module_defaults() -> None:
    module = parse(build([])).find("Controller/Modules/Module")
    assert (module.get("Name"), module.get("CatalogNumber")) == ("Local", "1756-L71")
    assert module.find("EKey").get("State") == "ExactMatch"
    assert module.find("Ports/Port/Bus").get("Size") == "13"


@pytest.mark.parametrize(("software", "major", "minor"), [("24.02", 24, 11), ("32.00", 32, 11), ("33.01", 33, 2)])
def test_revisions_stay_consistent(software: str, major: int, minor: int) -> None:
    root = parse(build([], software_revision=software, major_rev=major, minor_rev=minor))
    controller = root.find("Controller")
    module = controller.find("Modules/Module")
    assert (module.get("Major"), module.get("Minor")) == (controller.get("MajorRev"), controller.get("MinorRev"))
    assert root.get("SoftwareRevision").split(".")[0] == controller.get("MajorRev")


def test_software_revision_need_not_equal_major_dot_minor() -> None:
    root = parse(build([]))
    controller = root.find("Controller")
    assert root.get("SoftwareRevision") == "24.02"
    assert f"{controller.get('MajorRev')}.{controller.get('MinorRev')}" == "24.11"


def test_mismatched_software_revision_raises() -> None:
    with pytest.raises(ValueError, match="does not match"):
        build([], software_revision="32.00", major_rev=24)


def test_bus_size_parameter() -> None:
    module = parse(build([], bus_size=7)).find("Controller/Modules/Module")
    assert module.find("Ports/Port/Bus").get("Size") == "7"


def test_boolean_attributes_are_lowercase_true_or_false() -> None:
    root = parse(build([make_tag()]))
    seen = set()
    for element in root.iter():
        for name, value in element.attrib.items():
            if name in BOOLEAN_ATTRIBUTES:
                seen.add(name)
                assert value in ("true", "false"), f"{element.tag}.{name}={value}"
    assert seen == BOOLEAN_ATTRIBUTES


def test_safety_info_is_empty() -> None:
    safety = parse(build([])).find("Controller/SafetyInfo")
    assert len(safety) == 0
    assert dict(safety.attrib) == {}


def test_main_program_routine_and_task() -> None:
    controller = parse(build([])).find("Controller")
    program = controller.find("Programs/Program")
    assert program.get("Name") == "MainProgram"
    assert program.get("MainRoutineName") == "MainRoutine"
    assert program.find("Routines/Routine").get("Name") == "MainRoutine"
    task = controller.find("Tasks/Task")
    assert task.get("Name") == "MainTask"
    assert task.find("ScheduledPrograms/ScheduledProgram").get("Name") == "MainProgram"


def test_tags_are_controller_scoped_in_order() -> None:
    tags = [make_tag("P101_Run_Cmd"), make_tag("LT101_PV", "REAL"), make_tag("P101_Fault")]
    root = parse(build(tags))
    assert [tag.get("Name") for tag in root.findall("Controller/Tags/Tag")] == ["P101_Run_Cmd", "LT101_PV", "P101_Fault"]
    assert root.findall("Controller/Programs/Program/Tags/Tag") == []


def test_data_types_start_empty() -> None:
    assert len(parse(build([])).find("Controller/DataTypes")) == 0


def test_same_input_gives_identical_bytes() -> None:
    tags = [make_tag(), make_tag("LT101_PV", "REAL")]
    assert build(tags) == build(tags)


def test_building_twice_does_not_share_state() -> None:
    build([make_tag("A_Run_Cmd")])
    root = parse(build([make_tag("B_Run_Cmd")]))
    assert [tag.get("Name") for tag in root.findall("Controller/Tags/Tag")] == ["B_Run_Cmd"]
