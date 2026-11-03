"""Build a starter L5X file (Studio 5000 XML export format) containing generated tags.

Output follows one profile: a v24-style, non-safety 1756-L71 controller project.
Importing the output into Studio 5000 is UNTESTED. Treat it as a draft.
"""

from datetime import datetime

from lxml import etree

from logixconfig.models import DataType, Tag

DEFAULT_SOFTWARE_REVISION = "24.02"
DEFAULT_MAJOR_REV = 24
DEFAULT_MINOR_REV = 11
DEFAULT_BUS_SIZE = 13
OWNER = "logixconfig-ai"

XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
EXPORT_DATE_FORMAT = "%a %b %d %H:%M:%S %Y"

# Empty v24.02 non-safety controller project with a local 1756-L71, one program with
# an empty ladder routine, and one continuous task. Element order and fixed values
# follow a sample Studio 5000 export. ProjectSN is the zero default, not a serial.
# Attributes left empty are filled in by build_l5x.
L5X_SKELETON = """\
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="" TargetName="" TargetType="Controller"
    ContainsContext="false" Owner="" ExportDate="" ExportOptions="DecoratedData ForceProtectedEncoding AllProjDocTrans">
  <Controller Use="Target" Name="" ProcessorType="1756-L71" MajorRev="" MinorRev="" TimeSlice="20"
      ShareUnusedTimeSlice="1" ProjectCreationDate="" LastModifiedDate="" SFCExecutionControl="CurrentActive"
      SFCRestartPosition="MostRecent" SFCLastScan="DontScan" ProjectSN="16#0000_0000"
      MatchProjectToController="false" CanUseRPIFromProducer="false" InhibitAutomaticFirmwareUpdate="0"
      PassThroughConfiguration="EnabledWithAppend" DownloadProjectDocumentationAndExtendedProperties="true">
    <RedundancyInfo Enabled="false" KeepTestEditsOnSwitchOver="false" IOMemoryPadPercentage="90" DataTablePadPercentage="50"/>
    <Security Code="0" ChangesToDetect="16#ffff_ffff_ffff_ffff"/>
    <SafetyInfo/>
    <DataTypes/>
    <Modules>
      <Module Name="Local" CatalogNumber="1756-L71" Vendor="1" ProductType="14" ProductCode="92"
          Major="" Minor="" ParentModule="Local" ParentModPortId="1" Inhibited="false" MajorFault="true">
        <EKey State="ExactMatch"/>
        <Ports>
          <Port Id="1" Address="0" Type="ICP" Upstream="false">
            <Bus Size=""/>
          </Port>
        </Ports>
      </Module>
    </Modules>
    <AddOnInstructionDefinitions/>
    <Tags/>
    <Programs>
      <Program Name="MainProgram" TestEdits="false" MainRoutineName="MainRoutine" Disabled="false" UseAsFolder="false">
        <Tags/>
        <Routines>
          <Routine Name="MainRoutine" Type="RLL"/>
        </Routines>
      </Program>
    </Programs>
    <Tasks>
      <Task Name="MainTask" Type="CONTINUOUS" Priority="10" Watchdog="500" DisableUpdateOutputs="false" InhibitTask="false">
        <ScheduledPrograms>
          <ScheduledProgram Name="MainProgram"/>
        </ScheduledPrograms>
      </Task>
    </Tasks>
    <CST MasterID="0"/>
    <WallClockTime LocalTimeAdjustment="0" TimeZone="0"/>
    <Trends/>
    <DataLogs/>
    <TimeSynchronize Priority1="128" Priority2="128" PTPEnable="false"/>
  </Controller>
</RSLogix5000Content>
"""

# Raw format is a hex dump with no Format attribute (1756-RM014D p.42).
RAW_ZERO_DATA: dict[DataType, str] = {
    DataType.BOOL: "00",
    DataType.SINT: "00",
    DataType.INT: "00 00",
    DataType.DINT: "00 00 00 00",
    DataType.REAL: "00 00 00 00",
}


def radix_for(data_type: DataType) -> str:
    return "Float" if data_type is DataType.REAL else "Decimal"


def zero_value_for(data_type: DataType) -> str:
    return "0.0" if data_type is DataType.REAL else "0"


def default_software_revision(major_rev: int) -> str:
    return DEFAULT_SOFTWARE_REVISION if major_rev == DEFAULT_MAJOR_REV else f"{major_rev}.00"


def build_tag_element(tag: Tag, include_description: bool = True) -> etree._Element:
    # No Class attribute: it applies only to safety controller projects (1756-RM014D p.128).
    radix = radix_for(tag.data_type)
    element = etree.Element(
        "Tag",
        Name=tag.name,
        TagType="Base",
        DataType=tag.data_type.value,
        Radix=radix,
        Constant="false",
        ExternalAccess="Read/Write",
    )
    # Inside <Tag>, <Description> comes before <Data> (1756-RM014D p.122-123).
    if include_description and tag.description:
        description = etree.SubElement(element, "Description")
        description.text = _cdata(tag.description, tag.name)
    # Data formats must appear in the order raw, L5K, decorated. On import, a later
    # format overwrites earlier ones, so the decorated value wins over raw (1756-RM014D p.42).
    raw = etree.SubElement(element, "Data")
    raw.text = RAW_ZERO_DATA[tag.data_type]
    decorated = etree.SubElement(element, "Data", Format="Decorated")
    etree.SubElement(
        decorated,
        "DataValue",
        DataType=tag.data_type.value,
        Radix=radix,
        Value=zero_value_for(tag.data_type),
    )
    return element


def build_l5x(
    tags: list[Tag],
    controller_name: str,
    software_revision: str = DEFAULT_SOFTWARE_REVISION,
    major_rev: int = DEFAULT_MAJOR_REV,
    minor_rev: int = DEFAULT_MINOR_REV,
    bus_size: int = DEFAULT_BUS_SIZE,
    *,
    include_descriptions: bool = True,
    export_date: datetime | None = None,
) -> bytes:
    _check_revisions(software_revision, major_rev)
    root = etree.fromstring(L5X_SKELETON, etree.XMLParser(remove_blank_text=True))
    timestamp = (export_date or datetime.now()).strftime(EXPORT_DATE_FORMAT)
    _fill_content_header(root, controller_name, software_revision, timestamp)
    _fill_controller(root.find("Controller"), controller_name, major_rev, minor_rev, timestamp)
    _fill_local_module(root.find("Controller/Modules/Module"), major_rev, minor_rev, bus_size)
    tags_element = root.find("Controller/Tags")
    for tag in tags:
        tags_element.append(build_tag_element(tag, include_descriptions))
    return XML_DECLARATION + etree.tostring(root, encoding="UTF-8", xml_declaration=False, pretty_print=True)


def _check_revisions(software_revision: str, major_rev: int) -> None:
    software_major = software_revision.split(".", 1)[0]
    if software_major != str(major_rev):
        raise ValueError(
            f"SoftwareRevision '{software_revision}' does not match controller major revision {major_rev}"
        )


def _fill_content_header(root: etree._Element, controller_name: str, software_revision: str, timestamp: str) -> None:
    root.set("SoftwareRevision", software_revision)
    root.set("TargetName", controller_name)
    root.set("Owner", OWNER)
    root.set("ExportDate", timestamp)


def _fill_controller(
    controller: etree._Element, controller_name: str, major_rev: int, minor_rev: int, timestamp: str
) -> None:
    controller.set("Name", controller_name)
    controller.set("MajorRev", str(major_rev))
    controller.set("MinorRev", str(minor_rev))
    controller.set("ProjectCreationDate", timestamp)
    controller.set("LastModifiedDate", timestamp)


def _fill_local_module(module: etree._Element, major_rev: int, minor_rev: int, bus_size: int) -> None:
    module.set("Major", str(major_rev))
    module.set("Minor", str(minor_rev))
    module.find("Ports/Port/Bus").set("Size", str(bus_size))


def _cdata(text: str, tag_name: str) -> etree.CDATA:
    try:
        return etree.CDATA(text)
    except ValueError as error:
        raise ValueError(f"Tag '{tag_name}' description cannot be written as CDATA: {error}") from None
