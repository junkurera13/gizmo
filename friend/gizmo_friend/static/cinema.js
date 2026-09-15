import {mountDevice} from '/static/oddity-device.mjs';
const $ = id => document.getElementById(id);
const SESSION_KEY = 'gizmo-cinema-v1';
function stored(key) {
  try { return sessionStorage.getItem(key) || localStorage.getItem(key) || ''; }
  catch { return ''; }
}
function remember(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ }
  try { localStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ }
}
let key = stored(SESSION_KEY);
if (new URLSearchParams(location.search).has('embedded')) document.documentElement.classList.add('embedded');
mountDevice($('device')).catch(() => { $('device').dataset.loaded = 'true'; });
const video = $('film'), freeze = $('freeze');
let socket, peer, revision = 0, duration = 0, startTime = null, ending = false;
let recorder, microphone, held = false, recordingTimer;
let connectionPromise, displayedTitle = '', nextTitle = '', recordingRevision = 0, requestId = 0;
let warmPromise = null, warming = 0, warmed = 0, canPlay = false;
let timings = [];
const metrics = [];
window.gizmoFilmMetrics = metrics; // Local acceptance evidence; no provider credentials.
function phase(name, message) {
  document.body.dataset.phase = name;
  if (message !== undefined) $('status').textContent = message;
  $('pause').hidden = ['idle','paused','ended','error'].includes(name);
}
function captionAt(position) {
  for (const timing of timings) {
    const start = Number(timing.start) || 0;
    const end = Number(timing.end) || 0;
    if (start <= position && position < end) return String(timing.narration || '');
  }
  return '';
}
function setCaption(text = '') {
  const caption = $('caption');
  if (caption) caption.textContent = String(text || '').trim();
}
function send(value) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); }
function freezeFilm() {
  if (video.videoWidth && video.readyState >= 2) {
    freeze.width = video.videoWidth; freeze.height = video.videoHeight;
    freeze.getContext('2d').drawImage(video, 0, 0); freeze.hidden = false;
  }
  video.pause(); video.muted = true;
  $('resume').hidden = true;
}
function detach() { peer?.close(); peer = null; video.srcObject = null; startTime = null; warmed = 0; }
function interrupt() {
  ++requestId;freezeFilm(); canPlay=false; warmPromise=null; send({type:'interrupt',request_id:requestId}); detach();
  ending = true; $('title').textContent = displayedTitle; setCaption(); phase('paused', 'I’m listening. Where should we go from here?');
  $('ask').placeholder = 'Ask a question, change direction, or say “go on”…';
}
async function connect() {
  const headers = {};
  if (key) headers['x-gizmo-cinema'] = key;
  const response = await fetch('/cinema/session', {method:'POST', headers});
  if (!response.ok) { const body = await response.json(); throw new Error(body.detail || 'Could not connect.'); }
  key = (await response.json()).key; remember(SESSION_KEY, key);
  const connectedSocket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/cinema/ws?key=${encodeURIComponent(key)}`);
  socket=connectedSocket;
  socket.addEventListener('message', e => {if(socket===connectedSocket)handle(JSON.parse(e.data));});
  socket.addEventListener('close', () => {
    if(socket!==connectedSocket)return;
    freezeFilm(); detach(); connectionPromise = null;
    phase('paused', 'Connection closed. Send a question to reconnect.');
  });
  await new Promise((resolve,reject) => {
    socket.addEventListener('open', resolve, {once:true});
    socket.addEventListener('error', () => reject(new Error('Could not connect.')), {once:true});
    socket.addEventListener('close', () => reject(new Error('The preview connection was declined.')), {once:true});
  });
}
async function ensureConnection() {
  if (socket?.readyState === WebSocket.OPEN) return;
  if (!connectionPromise) connectionPromise = connect().catch(error => {connectionPromise=null;throw error;});
  await connectionPromise;
}
async function ask(text) {
  text = text.trim(); if (!text) return;
  const askId=++requestId;stopRecording();freezeFilm(); canPlay=false; duration=0; warmPromise=null; detach(); ending = true;
  phase('thinking', 'Thinking it through…'); nextTitle=''; setCaption(); timings=[];
  $('progress').firstElementChild.style.width='0%';$('progress').setAttribute('aria-valuenow','0');
  try {
    await ensureConnection();
    if(askId!==requestId)return;send({type:'ask',text,request_id:askId}); $('ask').value = '';
    $('ask').placeholder = 'You can ask something while it plays…';
  } catch(error) {phase('error',error.message);}
}
async function ensurePeer(generation) {
  if (warmed === generation && peer) return;
  if (warmPromise && warming === generation) return warmPromise;
  const work = (async () => {
    warming = generation;
    detach();
    startTime = null;
    ending = false;
    const pc = new RTCPeerConnection(); peer = pc;
    try {
      pc.addTransceiver('video',{direction:'recvonly'});
      pc.addTransceiver('audio',{direction:'recvonly'});
      const media = new MediaStream();
      pc.ontrack = e => {media.addTrack(e.track);video.srcObject=media;};
      pc.onconnectionstatechange = () => {
        if (peer === pc && pc.connectionState === 'failed') {
          interrupt();phase('error','The picture connection dropped. Try again.');
        }
      };
      await pc.setLocalDescription(await pc.createOffer());
      if (pc.iceGatheringState !== 'complete') await new Promise((resolve,reject) => {
        const timer=setTimeout(()=>reject(new Error('Connection timed out.')),8000);
        pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});
      });
      if (peer!==pc || revision!==generation) { pc.close(); return; }
      const response=await fetch(`/cinema/offer?key=${encodeURIComponent(key)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:generation,sdp:pc.localDescription.sdp})});
      if(!response.ok) throw new Error('Could not receive the film.');
      const answer=await response.json();
      if(peer!==pc || revision!==generation){pc.close();return;}
      await pc.setRemoteDescription(answer);
      warmed = generation;
    } catch(error) {
      if(peer===pc){interrupt();phase('error',error.message);}
      pc.close();
    }
  })();
  warmPromise = work;
  try { await work; }
  finally { if (warmPromise === work) warmPromise = null; }
}
async function startPlayback() {
  if (!canPlay || warmed !== revision || !duration || ending) return;
  video.muted = false;
  ending = false;
  try { await video.play(); } catch { $('resume').hidden = false; }
}
function handle(event) {
  if(event.request_id !== undefined && event.request_id !== null && event.request_id !== requestId)return;
  metrics.push({...event,at:performance.now()}); if(metrics.length>250)metrics.shift();
  if(event.type==='status'){revision=event.revision??revision;phase(event.phase,event.message);}
  if(event.type==='plan' && event.revision===revision) {nextTitle=event.title;ensurePeer(event.revision);}
  if(event.type==='ready' && event.revision===revision) {duration=event.duration;timings=Array.isArray(event.timings)?event.timings:[];canPlay=true;phase('preparing','Opening the scene…');ensurePeer(event.revision).then(startPlayback);}
  if(event.type==='playing' && event.revision===revision) {phase('preparing','The first frame is arriving…');}
  if(event.type==='buffering' && event.revision===revision) phase('buffering','Holding that thought…');
  if(event.type==='heard') $('ask').value=event.text;
  if(event.type==='paused'){revision=event.revision;}
  if(event.type==='ended'){freezeFilm();detach();revision=event.revision;setCaption();phase('ended','Where does that take your curiosity?');}
  if(event.type==='error'){freezeFilm();detach();ending=true;phase('error',event.message);}
}
// The media clock, not generation-complete messages, decides what the viewer has heard.
function presented(_now, metadata) {
  if(peer && !video.paused && video.readyState>=2 && !ending){
    if(startTime===null){displayedTitle=nextTitle;$('title').textContent=displayedTitle;startTime=metadata.mediaTime;metrics.push({type:'presented',at:performance.now()});}
    document.body.dataset.hasFilm='true';freeze.hidden=true;phase('playing');
    const elapsed=Math.max(0,metadata.mediaTime-startTime), progress=Math.min(100,elapsed/duration*100);
    setCaption(captionAt(elapsed));
    $('progress').style.setProperty('--progress',`${progress}%`);
    $('progress').firstElementChild.style.width=`${progress}%`;
    $('progress').setAttribute('aria-valuenow',Math.round(progress));
    if(duration && elapsed>=duration){ending=true;freezeFilm();send({type:'finished',revision});phase('ended','Where does that take your curiosity?');}
  }
  video.requestVideoFrameCallback(presented);
}
if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(presented);
else video.addEventListener('timeupdate',()=>{if(!video.paused){document.body.dataset.hasFilm='true';freeze.hidden=true;phase('playing');if(startTime===null)startTime=video.currentTime;const elapsed=Math.max(0,video.currentTime-startTime);setCaption(captionAt(elapsed));if(duration && elapsed>=duration&&!ending){ending=true;freezeFilm();send({type:'finished',revision});phase('ended','Where does that take your curiosity?');}}});
$('question').addEventListener('submit',e=>{e.preventDefault();ask($('ask').value);});
$('pause').onclick=interrupt;
$('resume').onclick=async()=>{video.muted=false;await video.play();$('resume').hidden=true;};
async function startRecording() {
  if(held)return;const captureRevision=++recordingRevision;held=true;interrupt();const voiceRequest=requestId;$('talk').classList.add('recording');phase('listening','Listening…');
  try{
    await ensureConnection();
    const captureStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
    if(!held || captureRevision!==recordingRevision){captureStream.getTracks().forEach(t=>t.stop());return;}
    microphone=captureStream;
    const mime=['audio/webm;codecs=opus','audio/mp4','audio/webm'].find(type=>MediaRecorder.isTypeSupported(type));
    const captureRecorder=new MediaRecorder(captureStream,mime?{mimeType:mime}:undefined);recorder=captureRecorder;const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=async()=>{
      captureStream.getTracks().forEach(t=>t.stop());
      if(voiceRequest!==requestId)return;
      const blob=new Blob(chunks,{type:captureRecorder.mimeType});
      if(blob.size>2_000_000){phase('error','That was a little long. Try a shorter question.');return;}
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);
      send({type:'audio',mime:blob.type,data:btoa(binary),request_id:voiceRequest});phase('thinking','Listening to your question…');
    };
    recorder.start();recordingTimer=setTimeout(stopRecording,20000);
  }catch(error){held=false;$('talk').classList.remove('recording');phase('error','Microphone unavailable. You can type your question.');}
}
function stopRecording(){held=false;++recordingRevision;clearTimeout(recordingTimer);$('talk').classList.remove('recording');if(recorder?.state==='recording')recorder.stop();}
for (const button of [$('talk'), $('ptt')]) {
  button.addEventListener('pointerdown',e=>{e.preventDefault();button.setPointerCapture(e.pointerId);startRecording();});
  ['pointerup','pointercancel','lostpointercapture'].forEach(kind=>button.addEventListener(kind,stopRecording));
}
$('talk').addEventListener('keydown',e=>{if([' ','Enter'].includes(e.key)&&!e.repeat){e.preventDefault();startRecording();}});
$('talk').addEventListener('keyup',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();stopRecording();}});
window.addEventListener('pagehide',()=>{send({type:'interrupt'});socket?.close();peer?.close();microphone?.getTracks().forEach(t=>t.stop());});
document.addEventListener('visibilitychange',()=>{if(document.hidden){stopRecording();if(peer)interrupt();}});
window.addEventListener('blur',stopRecording);
