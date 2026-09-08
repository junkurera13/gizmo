"""Import checked autorouting and fill grounded copper. KiCad Python required."""
from pathlib import Path
import xml.etree.ElementTree as ET
import pcbnew as p
ROOT=Path(__file__).resolve().parent
f=ROOT/'Gizmo_Hub.kicad_pcb'
b=p.LoadBoard(str(f))
assert p.ImportSpecctraSES(b,str(ROOT/'outputs/Gizmo_Hub.ses'))
for fp in b.GetFootprints():
    if fp.GetReference().startswith('H'):
        fp.SetAttributes(fp.GetAttributes()|p.FP_BOARD_ONLY)
# Same-sheet local label names are represented with '/' by KiCad's netlist.
for n in b.GetNetInfo().NetsByNetcode().values():
    if n.GetNetname() and not n.GetNetname().startswith('/'):
        n.SetNetname('/'+n.GetNetname())
gnd=next(n for n in b.GetNetInfo().NetsByNetcode().values() if n.GetNetname()=='/GND')
tree=ET.parse(ROOT/'outputs/netlist.xml')
for n in tree.findall('.//nets/net'):
    if any(node.get('ref')=='J1' and node.get('pin')=='9' for node in n.findall('node')):
        nc=b.FindNet(n.get('name'))
        if nc is None:
            nc=p.NETINFO_ITEM(b,n.get('name'));b.Add(nc)
        for fp in b.GetFootprints():
            if fp.GetReference()=='J1':
                for pad in fp.Pads():
                    if pad.GetNumber()=='9':pad.SetNet(nc)
OLD_ZONES=list(b.Zones())
for z in OLD_ZONES:
    if not z.GetIsRuleArea():b.Remove(z)
for layer in [p.F_Cu,p.B_Cu]:
    z=p.ZONE(b);z.SetLayer(layer);z.SetNet(gnd)
    z.SetZoneName('GND_FRONT' if layer==p.F_Cu else 'GND_REAR')
    z.SetLocalClearance(p.FromMM(.2));z.SetMinThickness(p.FromMM(.25))
    z.SetThermalReliefGap(p.FromMM(.25));z.SetThermalReliefSpokeWidth(p.FromMM(.3))
    z.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
    poly=z.Outline();poly.NewOutline()
    for x,y in [(.5,.5),(74.5,.5),(74.5,69.5),(.5,69.5)]:poly.Append(p.FromMM(x),p.FromMM(y))
    b.Add(z)
b.BuildConnectivity()
p.ZONE_FILLER(b).Fill(b.Zones())
p.SaveBoard(str(f),b)
print('Imported routes, matched schematic net names, filled both GND planes.')
