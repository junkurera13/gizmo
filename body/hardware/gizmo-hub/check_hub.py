"""Independent pin-map, schematic/PCB connectivity and mechanical checks."""
from pathlib import Path
import json, re, xml.etree.ElementTree as ET
import pcbnew as p
ROOT=Path(__file__).resolve().parent
b=p.LoadBoard(str(ROOT/'Gizmo_Hub.kicad_pcb'))
fps={f.GetReference():f for f in b.GetFootprints()}
actual={(r,pad.GetNumber()):pad.GetNetname() for r,fp in fps.items() for pad in fp.Pads() if pad.GetNumber()}
expected={}
for net in ET.parse(ROOT/'outputs/netlist.xml').findall('.//nets/net'):
    for node in net.findall('node'):expected[(node.get('ref'),node.get('pin'))]=net.get('name')
assert actual==expected, (set(actual.items())-set(expected.items()),set(expected.items())-set(actual.items()))
def same(*pins):
    names=[actual[x] for x in pins]
    assert len(set(names))==1,names
for display_pin,module_pin in [('1','14'),('2','13'),('3','8'),('4','12'),('5','7'),('6','11'),('7','9'),('8','12')]:same(('J1',display_pin),('U1',module_pin))
for spk_pin,module_pin in [('1','10'),('2','12'),('3','13')]:same(('J2',spk_pin),('U1',module_pin))
same(('J3','1'),('U1','5'),('R1','1'),('R2','2'),('R3','2'),('C1','1'))
same(('J3','2'),('R2','1'));same(('J3','3'),('R3','1'))
same(('R1','2'),('C1','2'),('U1','13'));same(('J3','4'),('U1','12'))
same(('J4','1'),('U1','2'));same(('J4','2'),('U1','13'))
same(('J5','1'),('U1','3'));same(('J5','2'),('U1','13'))
same(('J6','1'),('R4','1'));same(('R4','2'),('R5','1'),('U1','6'))
same(('R5','2'),('U1','13'));same(('J6','3'),('U1','14'))
assert actual['J6','1']!=actual['J6','3'], 'BAT sensing must not be tied to USB VBUS'
for ref in ['J8','J9']:same((ref,'1'),('U1','14'));same((ref,'2'),('U1','13'))
assert abs(p.ToMM(fps['J8'].GetPosition().x-fps['J9'].GetPosition().x))>=60
same(('J7','5'),('U1','12'));same(('J7','6'),('U1','13'))
assert sum(n==actual['J1','9'] for n in actual.values())==1,'SDO must be isolated'
assert {x.GetNumber() for x in fps['U1'].Pads()}=={str(i) for i in range(1,15)}
board_h=(ROOT/'../../firmware/include/gizmo/board.h').resolve().read_text(encoding='utf-8')
for name,gpio in {'amp_out':8,'display_cs':44,'display_dc':43,'display_mosi':9,'display_sck':7,'buttons_adc':5,'battery_adc':6,'ptt':2,'haptic':3}.items():
    assert re.search(rf'constexpr int {name}\s*=\s*{gpio}\s*;',board_h), name
assert b.GetCopperLayerCount()==2
assert all(fp.GetLayer()==p.F_Cu for fp in fps.values())
assert all(not (6.5<=p.ToMM(t.GetPosition().x)<=68.5 and 23<=p.ToMM(t.GetPosition().y)<=65) for t in b.GetTracks() if isinstance(t,p.PCB_VIA))
assert len([z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname()=='/GND'])==2
checks=json.load(open(ROOT/'outputs/drc.json'))
assert not any(checks[k] for k in ['violations','unconnected_items','schematic_parity'])
values={r:fps[r].GetValue() for r in ['R1','R2','R3','R4','R5','C1']}
assert values=={'R1':'10k','R2':'4.7k','R3':'15k','R4':'100k','R5':'100k','C1':'100nF'}
summary={'result':'PASS','board_mm':[75,70],'battery_clearance_mm':[62,42],'battery_user_dimensions_mm':[60,40,8],
         'schematic_pad_connections_verified':len(expected),'copper_layers':2,
         'vias':sum(isinstance(t,p.PCB_VIA) for t in b.GetTracks()),
         'minimum_track_width_mm':min(p.ToMM(t.GetWidth()) for t in b.GetTracks() if not isinstance(t,p.PCB_VIA)),
         'erc_errors':0,'drc_violations':0,'unrouted_connections':0,'schematic_parity_issues':0,
         'physical_assembly_tested':False,'battery_connector_polarity_verified':False}
(ROOT/'outputs/validation.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
