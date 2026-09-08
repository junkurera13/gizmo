"""Generate the Gizmo interconnect in KiCad 10. Run with KiCad's python.exe.
Power choice is intentionally recorded in README, not inferred from BAT voltage.
"""
from pathlib import Path
import json, uuid, shutil
import pcbnew as p
IO = p.PCB_IO_KICAD_SEXPR()
p.FootprintSave = lambda path, fp: IO.FootprintSave(path, fp)

ROOT = Path(__file__).resolve().parent
LIB = ROOT / 'Gizmo.pretty'
LIB.mkdir(exist_ok=True)
OUT = ROOT / 'outputs'
OUT.mkdir(exist_ok=True)
NAME = 'Gizmo_Hub'
SCHEMA_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, 'gizmo/hub/schematic'))
def uid(s): return str(uuid.uuid5(uuid.NAMESPACE_URL, 'gizmo/hub/'+s))
def q(s): return json.dumps(str(s), ensure_ascii=False)
def v(x,y): return p.VECTOR2I(p.FromMM(x),p.FromMM(y))
B = p.BOARD()
B.SetCopperLayerCount(2)
ds=B.GetDesignSettings()
ds.m_MinClearance=p.FromMM(.2)
ds.m_TrackMinWidth=p.FromMM(.25)
ds.m_ViasMinSize=p.FromMM(.6)
ds.m_MinThroughDrill=p.FromMM(.3)
ds.SetBoardThickness(p.FromMM(1.6))
nets={}
def net(s):
    if s and s not in nets:
        n=p.NETINFO_ITEM(B,s); B.Add(n); nets[s]=n
    return nets.get(s)
def text(s,x,y,size=.85,layer=p.F_SilkS,align='center'):
    size=max(size,.8)
    t=p.PCB_TEXT(B);t.SetText(s);t.SetPosition(v(x,y));t.SetTextSize(v(size,size));t.SetTextThickness(p.FromMM(.13));t.SetLayer(layer)
    if align=='left': t.SetHorizJustify(p.GR_TEXT_H_ALIGN_LEFT)
    if align=='right': t.SetHorizJustify(p.GR_TEXT_H_ALIGN_RIGHT)
    if layer==p.B_SilkS:t.SetMirrored(True)
    B.Add(t);return t
def line(a,b,layer=p.F_SilkS,width=.15,fp=None):
    z=p.PCB_SHAPE(fp or B);z.SetShape(p.SHAPE_T_SEGMENT);z.SetStart(v(*a));z.SetEnd(v(*b));z.SetLayer(layer);z.SetWidth(p.FromMM(width));(fp or B).Add(z)
def rect(x1,y1,x2,y2,layer=p.F_SilkS,fp=None):
    for a,b in [((x1,y1),(x2,y1)),((x2,y1),(x2,y2)),((x2,y2),(x1,y2)),((x1,y2),(x1,y1))]:line(a,b,layer,fp=fp)
rect(0,0,75,70,p.Edge_Cuts)
components=[]
def add(fp,ref,value,x,y,pins,fpname):
    fp.SetReference(ref);fp.SetValue(value);fp.SetPosition(v(x,y));fp.SetFPID(p.LIB_ID('Gizmo',fpname))
    fp.SetPath(p.KIID_PATH('/'+SCHEMA_ID+'/'+uid(ref)))

    fp.Reference().SetVisible(False);fp.Value().SetVisible(False)
    for pad in fp.Pads():
        n=pins.get(pad.GetNumber())
        if n:pad.SetNet(net(n))
    B.Add(fp)
    components.append(dict(ref=ref,value=value,pins=pins,footprint='Gizmo:'+fpname,uuid=uid(ref)))
    return fp
def header(ref,value,x,y,pins,labels,horizontal=False,left=False):
    name=f'Header_1x{len(pins):02d}_'+('H' if horizontal else 'V')
    fp=p.FOOTPRINT(B); fp.SetAttributes(p.FP_THROUGH_HOLE)
    for i in range(len(pins)):
        pad=p.PAD(fp);pad.SetNumber(str(i+1));pad.SetAttribute(p.PAD_ATTRIB_PTH);pad.SetShape(p.PAD_SHAPE_RECT if i==0 else p.PAD_SHAPE_CIRCLE)
        pad.SetSize(v(1.8,1.8));pad.SetDrillSize(v(1,1));pad.SetLayerSet(p.PAD.PTHMask())
        pad.SetPosition(v(i*2.54 if horizontal else 0,0 if horizontal else i*2.54));fp.Add(pad)
    xx=(len(pins)-1)*2.54 if horizontal else 0; yy=0 if horizontal else (len(pins)-1)*2.54
    rect(-1.25,-1.25,xx+1.25,yy+1.25,p.F_SilkS,fp)
    rect(-1.5,-1.5,xx+1.5,yy+1.5,p.F_CrtYd,fp)
    fp.SetFPID(p.LIB_ID('Gizmo',name));p.FootprintSave(str(LIB),fp)
    fp=add(fp,ref,value,x,y,{str(i+1):n for i,n in enumerate(pins)},name)
    for i,label in enumerate(labels):
        if horizontal:text(label,x+i*2.54,y-(2.6 if i%2 else 4.1),.75)
        else:text(label,x+(-2 if left else 2),y+i*2.54,.80,align='right' if left else 'left')
    text(ref+' '+value,x+(xx/2 if horizontal else (-2 if left else 2)),y-6.1 if horizontal else y-2.8,.95,align='center' if horizontal else ('right' if left else 'left'))
    components[-1]['pin_names']={str(i+1):s for i,s in enumerate(labels)}
    return fp

# Manufacturer castellated geometry; omit unused underside debug/USB contacts.
src=ROOT/'vendor/footprints/Seeed_Studio_XIAO_Series.pretty'
fp=p.FootprintLoad(str(src),'XIAO-ESP32-S3-SMD')
SOURCE_GRAPHICS=list(fp.GraphicalItems())
for g in SOURCE_GRAPHICS:
    if g.GetLayer()==p.F_SilkS:g.SetLayer(p.F_Fab)
line((1.8,-21),(15.9,-21),fp=fp)
line((1.8,0),(15.9,0),fp=fp)
REMOVED_PADS = list(fp.Pads())  # retain wrappers until board save (KiCad 10 SWIG)
for pad in REMOVED_PADS:
    if int(pad.GetNumber())>=15: fp.Remove(pad)
# Power via isolated external 5 V or USB; no contact to XIAO BAT charger.
fp.SetFPID(p.LIB_ID('Gizmo','XIAO_ESP32S3_Castellated'))
p.FootprintSave(str(LIB),fp)
U={'1':'D0_GPIO1_UNUSED','2':'PTT_D1_GPIO2','3':'HAPTIC_D2_GPIO3','4':'D3_GPIO4_UNUSED',
   '5':'BUTTON_ADC_D4_GPIO5','6':'BAT_SENSE_D5_GPIO6','7':'DISP_DC_D6_GPIO43','8':'DISP_CS_D7_GPIO44',
   '9':'DISP_SCK_D8_GPIO7','10':'SPK_IN_D9_GPIO8','11':'DISP_SDI_D10_GPIO9','12':'3V3','13':'GND','14':'5V'}
u=add(fp,'U1','XIAO ESP32S3 Sense',28.6,22.1,U,'XIAO_ESP32S3_Castellated')
for pad in u.Pads():
    i=int(pad.GetNumber());xy=pad.GetPosition();label=U[str(i)].replace('_GPIO',' /G').replace('DISP_','').replace('BUTTON_ADC_','ADC/').replace('BAT_SENSE_','BAT/').replace('_UNUSED','')
    text(label,26.6 if i<=7 else 49, p.ToMM(xy.y),.70,align='right' if i<=7 else 'left')
text('U1 XIAO ESP32S3 SENSE',37.5,24,.85)
text('CAMERA + MIC ON MODULE',37.5,26,.8)
text('USB / CAMERA END',37.5,2.5,.75)
# All external modules are headers only.
header('J1','DISPLAY',71,16.5,['5V','GND','DISP_CS_D7_GPIO44','3V3','DISP_DC_D6_GPIO43','DISP_SDI_D10_GPIO9','DISP_SCK_D8_GPIO7','3V3',None],
       ['VCC / 5V VUSB','GND','CS / D7 / GPIO44','RESET / 3V3','DC / D6 / GPIO43','SDI / D10 / GPIO9','SCK / D8 / GPIO7','LED / 3V3','SDO / NC'],left=True)
text('T_*: NO CONNECTION',60,39,.8)
header('J2','SPEAKER 3885',71,43,['SPK_IN_D9_GPIO8','3V3','GND'],['SPK_IN / D9 / GPIO8','SPK_3V3','SPK_GND'],left=True)
header('J3','BUTTONS',4,31,['BUTTON_ADC_D4_GPIO5','BUTTON_DOWN','BUTTON_SEL','3V3','GND'],['UP / D4 / GPIO5','DOWN','SEL','3V3 (SW COMMON)','GND'])
header('J4','PTT',4,22,['PTT_D1_GPIO2','GND'],['PTT / D1 / GPIO2','PTT_GND'])
header('J5','HAPTIC',4,49,['HAPTIC_D2_GPIO3','GND','3V3'],['HAPTIC_D2 / GPIO3','HAPTIC_GND','HAPTIC_3V3'])
header('J6','PWR',12,66,['BAT+','GND','5V'],['BAT+','GND','5V'],horizontal=True)
text('BAT SENSE / SWITCHED VUSB IN',19,57.5,.72)
header('J7','UTIL',35,66,['5V','5V','GND','GND','3V3','GND'],['5V','5V','GND','GND','3V3','GND'],horizontal=True)
header('J8','5V AUX A',4,10,['5V','GND'],['5V','GND'])
header('J9','5V AUX B',71,8,['5V','GND'],['5V','GND'],left=True)
header('J10','FUTURE',71,55,['D0_GPIO1_UNUSED','D3_GPIO4_UNUSED'],['UNUSED D0 / GPIO1','UNUSED D3 / GPIO4'],left=True)
for name,x,y in [('H1',3,3),('H2',72,3),('H3',3,67),('H4',72,67)]:
    fp=p.FootprintLoad('C:/Program Files/KiCad/10.0/share/kicad/footprints/MountingHole.pretty','MountingHole_2.2mm_M2')
    fp.SetReference(name);fp.SetValue('M2 NPTH');fp.SetPosition(v(x,y));fp.Reference().SetVisible(False);fp.Value().SetVisible(False);B.Add(fp)
    text(name,x+(3 if x<10 else -3),y,.7)

def passive(ref,value,x,y,n1,n2,kind='R'):
    lib='Resistor_SMD' if kind=='R' else 'Capacitor_SMD';name=('R' if kind=='R' else 'C')+'_0805_2012Metric'
    fp=p.FootprintLoad('C:/Program Files/KiCad/10.0/share/kicad/footprints/'+lib+'.pretty',name)
    fp.SetFPID(p.LIB_ID('Gizmo',name));p.FootprintSave(str(LIB),fp)
    add(fp,ref,value,x,y,{'1':n1,'2':n2},name)
    text(ref+' '+value,x,y-1.8,.75)
passive('R1','10k',26,34,'BUTTON_ADC_D4_GPIO5','GND')
passive('R2','4.7k',26,39,'BUTTON_DOWN','BUTTON_ADC_D4_GPIO5')
passive('R3','15k',26,44,'BUTTON_SEL','BUTTON_ADC_D4_GPIO5')
passive('C1','100nF',34,34,'BUTTON_ADC_D4_GPIO5','GND','C')
passive('R4','100k',36,43,'BAT+','BAT_SENSE_D5_GPIO6')
passive('R5','100k',44,43,'BAT_SENSE_D5_GPIO6','GND')
text('BAT_SENSE / D5',40,46,.8)
text('ADC LADDER',30,29.5,.9)
text('GIZMO / HUB REV A',39,51,1.25)
text('75 x 70 mm | 2 LAYER',39,53.5,.85)
text('ALL MODULES OFF-BOARD EXCEPT U1',39,56,.7)
# Single front SMD test points; back remains component-free.
for ref,label,x,y,n in [('TP1','3V3',35,19,'3V3'),('TP2','GND',40,19,'GND')]:
    # Keep test points outside module courtyard.
    y=30
    fp=p.FOOTPRINT(B);pad=p.PAD(fp);pad.SetNumber('1');pad.SetAttribute(p.PAD_ATTRIB_SMD);pad.SetShape(p.PAD_SHAPE_CIRCLE);pad.SetSize(v(1.5,1.5));pad.SetLayerSet(p.PAD.SMDMask());fp.Add(pad)
    fp.SetAttributes(p.FP_SMD);fp.SetFPID(p.LIB_ID('Gizmo','TestPoint_1.5mm'));p.FootprintSave(str(LIB),fp)
    add(fp,ref,label,x,y,{'1':n},'TestPoint_1.5mm');text(ref+' '+label,x,y-(1.6 if ref=='TP1' else 3),.7)
# Battery space excludes rear parts and through-board vias/pads. Copper under
# soldermask is permitted; add insulating sheet before pouch installation.
z=p.ZONE(B);z.SetLayer(p.B_Cu);z.SetIsRuleArea(True);z.SetZoneName('BATTERY_62x42_CLEARANCE')
z.SetDoNotAllowFootprints(True);z.SetDoNotAllowPads(True);z.SetDoNotAllowVias(True);z.SetDoNotAllowTracks(False);z.SetDoNotAllowZoneFills(False)
poly=z.Outline();poly.NewOutline()
for x,y in [(6.5,23),(68.5,23),(68.5,65),(6.5,65)]:poly.Append(int(p.FromMM(x)),int(p.FromMM(y)))
B.Add(z)
rect(6.5,23,68.5,65,p.B_SilkS)
text('BATTERY 60 x 40 x 8 mm',37.5,40,1.25,p.B_SilkS)
text('62 x 42 mm CLEARANCE',37.5,43,1,p.B_SilkS)
text('INSULATING SHEET + FOAM SPACER',37.5,46,.9,p.B_SilkS)
text('NO PINS / COMPONENTS / VIAS',37.5,49,.9,p.B_SilkS)
for i,(s,x) in enumerate([('BAT+',12),('GND',14.54),('5V',17.08)]):text(s,x,62 if i%2==0 else 63.5,.7,p.B_SilkS)
text('GIZMO HUB A',37.5,68,1,p.B_SilkS)
p.SaveBoard(str(ROOT/(NAME+'.kicad_pcb')),B)
p.ExportSpecctraDSN(B,str(OUT/(NAME+'.dsn')))
dsnpath=OUT/(NAME+'.dsn')
dsn=dsnpath.read_text().replace('(width 200)','(width 250)')
start=dsn.index('    (class kicad_default')
end=dsn.index('\n  )\n  (wiring',start)
signals=[n for n in nets if n not in ['5V','3V3','GND']]
dsn=dsn[:start]+f'''    (class signals {' '.join(signals)}
      (circuit (use_via "Via[0-1]_600:300_um"))
      (rule (width 250) (clearance 200)))
    (class power 5V 3V3 GND
      (circuit (use_via "Via[0-1]_600:300_um"))
      (rule (width 600) (clearance 200)))'''+dsn[end:]
dsnpath.write_text(dsn)
(ROOT/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "Gizmo")(type "KiCad")(uri "${KIPRJMOD}/Gizmo.pretty")(options "")(descr "Gizmo local footprints")))')
(ROOT/(NAME+'.kicad_pro')).write_text(json.dumps({'meta':{'filename':NAME+'.kicad_pro','version':1},'board':{'design_settings':{'rules':{'min_clearance':.2,'min_track_width':.25,'min_via_diameter':.6,'min_through_hole_diameter':.3},'defaults':{'board_outline_line_width':.05}}},'net_settings':{'classes':[{'name':'Default','clearance':.2,'track_width':.25,'via_diameter':.6,'via_drill':.3,'microvia_diameter':.3,'microvia_drill':.1,'diff_pair_width':.25,'diff_pair_gap':.25,'diff_pair_via_gap':.25}]},'text_variables':{'REVISION':'A'}},indent=2))
(ROOT/'manifest.json').write_text(json.dumps(components,indent=2))

# Self-contained schematic, named pins + explicit same-sheet net labels.
symbols=[];instances=[];wires=[];labels=[];notes=[]
def note(s,x,y,size=1.27):notes.append(f'(text {q(s)} (at {x} {y} 0) (effects (font (size {size} {size})) (justify left)) (uuid {q(uid("note"+s))}))')
def schematic_component(c,x,y,kind='header'):
    ref=c['ref'];ns=c['pins'];n=len(ns);sym=ref+'_symbol';pins=[]
    if kind=='module':
        h=45
        for i,(num,nn) in enumerate(ns.items()):
            idx=int(num);left=idx<=7;px=-20.32 if left else 20.32;py=15.24-(idx-1 if left else 14-idx)*5.08
            pn=nn[nn.index('D'):].replace('_GPIO',' / GPIO').replace('_UNUSED','') if '_GPIO' in nn else nn
            if '_GPIO' in nn:
                import re
                pn=re.search(r'D\d+_GPIO\d+',nn).group().replace('_',' / ')
            typ='power_out' if nn=='3V3' else ('power_in' if nn in ['5V','GND'] else 'bidirectional')
            pins.append((num,pn,nn,px,py,0 if left else 180,typ))
        box=(-15.24,20.32,15.24,-20.32)
    elif kind=='passive':
        pins=[('1','~',ns['1'],-5.08,0,0,'passive'),('2','~',ns['2'],5.08,0,180,'passive')];box=(-2.54,1.016,2.54,-1.016)
    else:
        for i,(num,nn) in enumerate(ns.items()):
            pn=c.get('pin_names',{}).get(num,nn or 'NC').split(' / GPIO')[0]
            typ='power_out' if ref=='J6' and nn in ['5V','GND'] else 'passive'
            pins.append((num,pn,nn,-5.08,-i*5.08,0,typ))
        box=(0,2.54,22.86,-(n-1)*5.08-2.54)
    a,b,d,e=box
    graphics=f'(rectangle (start {a} {b}) (end {d} {e}) (stroke (width .254) (type default)) (fill (type background)))'
    if ref.startswith('C'):
        graphics=''.join(f'(polyline (pts (xy {xx} -2.54)(xy {xx} 2.54)) (stroke (width .254)(type default)) (fill (type none)))' for xx in [-1.27,1.27])
    plen=3.81 if ref.startswith('C') else (2.54 if kind=='passive' else 5.08)
    pintext=''.join(f'(pin {typ} line (at {px} {py} {angle}) (length {plen}) (name {q(pn)} (effects (font (size 1.0 1.0)))) (number {q(num)} (effects (font (size 1 1)))))' for num,pn,nn,px,py,angle,typ in pins)
    lib=f'(symbol {q("Gizmo:"+sym)} (pin_names (offset .8)) (in_bom yes) (on_board yes) (property "Reference" {q(ref)} (at 0 5.08 0) (effects (font (size 1.27 1.27)))) (property "Value" {q(c["value"])} (at 0 2.54 0) (effects (font (size 1.27 1.27)))) (symbol {q(sym+"_0_1")} {graphics}) (symbol {q(sym+"_1_1")} {pintext}))'
    symbols.append(lib)
    instances.append(f'(symbol (lib_id {q("Gizmo:"+sym)}) (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid {q(c["uuid"])}) (property "Reference" {q(ref)} (at {x+3} {y-b-5.08} 0) (effects (font (size 1.27 1.27)))) (property "Value" {q(c["value"])} (at {x+3} {y-b-2.54} 0) (effects (font (size 1.27 1.27)))) (property "Footprint" {q(c["footprint"])} (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide)) '+''.join(f'(pin {q(num)} (uuid {q(uid(ref+"pin"+num))}))' for num,*_ in pins)+f' (instances (project {q(NAME)} (path {q("/"+SCHEMA_ID)} (reference {q(ref)}) (unit 1)))))')
    for num,pn,nn,px,py,angle,typ in pins:
        xx=round(x+px,4);yy=round(y-py,4)
        if nn:
            end=xx-7.62 if angle==0 else xx+7.62
            wires.append(f'(wire (pts (xy {xx} {yy})(xy {end} {yy})) (stroke (width 0)(type default)) (uuid {q(uid(ref+"wire"+num))}))')
            labels.append(f'(label {q(nn)} (at {end} {yy} 0) (effects (font (size 1 1)) (justify {"right" if angle==0 else "left"} bottom)) (uuid {q(uid(ref+"label"+num))}))')
        else:labels.append(f'(no_connect (at {xx} {yy}) (uuid {q(uid(ref+"nc"+num))}))')
positions={'U1':(91.44,68.58,'module'),'J1':(269.24,40.64,'header'),'J2':(269.24,109.22,'header'),'J3':(269.24,149.86,'header'),'J4':(269.24,198.12,'header'),'J5':(269.24,233.68,'header'),
'J6':(58.42,147.32,'header'),'J7':(58.42,190.5,'header'),'J8':(167.64,190.5,'header'),'J9':(167.64,220.98,'header'),'J10':(167.64,254,'header'),
'R1':(180.34,43.18,'passive'),'R2':(180.34,63.5,'passive'),'R3':(180.34,83.82,'passive'),'C1':(180.34,104.14,'passive'),
'R4':(180.34,137.16,'passive'),'R5':(180.34,157.48,'passive'),'TP1':(58.42,246.38,'header'),'TP2':(58.42,269.24,'header')}
for c in components:schematic_component(c,*positions[c['ref']])
note('GIZMO / HANDHELD INTERCONNECT / REV A',20,15,2.54)
note('GPIO mapping is fixed. All switches, display, speaker and haptic driver are OFF BOARD.',20,22)
note('U1: USB at top; Sense camera + PDM stay on module. SD unused; GPIO21 held HIGH.',20,108,1.05)
note('D2/GPIO3 is a strap: off-board 1k -> C1815 base. No pull-up on hub.',20,114,1.05)
note('POWER: TP4056 OUT+ -> off-board switch -> 5V/VUSB. OUT- -> GND. BAT+ senses OUT+.',20,122,1.05)
note('XIAO underside BAT/USB/debug pads intentionally NOT contacted. Do not parallel chargers.',20,128,1.05)
note('SWITCHES: UP / DOWN / SEL close to 3V3; PTT to GND.',245,271,1.05)
note('Ladder: idle 0V; SEL 1.32V; DOWN 2.24V; UP 3.3V. BAT divider = 2.0.',20,280,1.05)
schematic=f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {q(SCHEMA_ID)}) (paper "A3") (title_block (title "Gizmo interconnect hub") (date "2026-09-08") (rev "A") (company "Gizmo")) (lib_symbols '+''.join(symbols)+')'+''.join(wires+labels+notes+instances)+' (embedded_fonts no))'
(ROOT/(NAME+'.kicad_sch')).write_text(schematic,encoding='utf-8')
(ROOT/'Gizmo.kicad_sym').write_text('(kicad_symbol_lib (version 20241209) (generator "kicad_symbol_editor") '+''.join(s.replace('(symbol "Gizmo:', '(symbol "',1) for s in symbols)+')')
(ROOT/'sym-lib-table').write_text('(sym_lib_table (version 7) (lib (name "Gizmo")(type "KiCad")(uri "${KIPRJMOD}/Gizmo.kicad_sym")(options "")(descr "Local hub symbols")))')
print('Generated',NAME,'75 x 70 mm;',len(components),'electrical components')
