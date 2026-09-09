const $ = id => document.getElementById(id);
const video = $('film'), freeze = $('freeze');
let socket, peer, revision = 0, duration = 0, startTime = null, ending = false;
let recorder, microphone, held = false, recordingTimer;
let connectionPromise, muted = false, displayedTitle = '', nextTitle = '', recordingRevision = 0, requestId = 0;
const metrics = [];
window.gizmoFilmMetrics = metrics; // Local acceptance evidence; no provider credentials.
function phase(name, message) {
  document.body.dataset.phase = name;
  $('welcome').inert = name !== 'idle';
  $('welcome').setAttribute('aria-hidden', name !== 'idle');
  if (message !== undefined) $('status').textContent = message;
  $('pause').hidden = ['idle','paused','ended','error'].includes(name);
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
function detach() { peer?.close(); peer = null; video.srcObject = null; startTime = null; }
function interrupt() {
  ++requestId;freezeFilm(); send({type:'interrupt',request_id:requestId}); detach();
  ending = true; $('title').textContent = displayedTitle; phase('paused', 'I’m listening. Where should we go from here?');
  $('ask').placeholder = 'Ask a question, change direction, or say “go on”…';
}
async function connect(code = '') {
  const response = await fetch('/cinema/session', {method:'POST', headers:{'x-gizmo-access':code}});
  if (response.status === 401) { $('access').showModal(); throw new Error('Enter the preview access code.'); }
  if (!response.ok) { const body = await response.json(); throw new Error(body.detail || 'Could not connect.'); }
  const connectedSocket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/cinema/ws`);
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
  const askId=++requestId;stopRecording();freezeFilm(); detach(); ending = true;
  phase('thinking', 'Thinking it through…'); nextTitle='';
  $('progress').firstElementChild.style.width='0%';$('progress').setAttribute('aria-valuenow','0');
  try {
    await ensureConnection();
    if(askId!==requestId)return;send({type:'ask',text,request_id:askId}); $('ask').value = '';
    $('ask').placeholder = 'You can ask something while it plays…';
  } catch(error) {phase('error',error.message);}
}
async function attach(event) {
  const generation = event.revision;
  detach(); duration = event.duration; startTime = null; ending = false;
  const pc = new RTCPeerConnection(); peer = pc;
  pc.addTransceiver('video',{direction:'recvonly'});
  pc.addTransceiver('audio',{direction:'recvonly'});
  const media = new MediaStream();
  pc.ontrack = e => {media.addTrack(e.track);video.srcObject=media;};
  pc.onconnectionstatechange = () => {
    if (peer === pc && pc.connectionState === 'failed') {
      interrupt();phase('error','The picture connection dropped. Try again.');
    }
  };
  try {
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== 'complete') await new Promise((resolve,reject) => {
      const timer=setTimeout(()=>reject(new Error('Connection timed out.')),8000);
      pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});
    });
    const response=await fetch('/cinema/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:generation,sdp:pc.localDescription.sdp})});
    if(!response.ok) throw new Error('Could not receive the film.');
    const answer=await response.json();
    if(peer!==pc || revision!==generation){pc.close();return;}
    await pc.setRemoteDescription(answer);
    video.muted=muted;
    try{await video.play();}catch{$('resume').hidden=false;}
  } catch(error) {
    if(peer===pc){interrupt();phase('error',error.message);}
    pc.close();
  }
}
function handle(event) {
  if(event.request_id !== undefined && event.request_id !== null && event.request_id !== requestId)return;
  metrics.push({...event,at:performance.now()}); if(metrics.length>250)metrics.shift();
  if(event.type==='status'){revision=event.revision??revision;phase(event.phase,event.message);}
  if(event.type==='plan' && event.revision===revision) nextTitle=event.title;
  if(event.type==='ready' && event.revision===revision) {phase('preparing','Opening the scene…');attach(event);}
  if(event.type==='playing' && event.revision===revision) {phase('preparing','The first frame is arriving…');}
  if(event.type==='buffering' && event.revision===revision) phase('buffering','Holding that thought…');
  if(event.type==='heard') $('ask').value=event.text;
  if(event.type==='paused'){revision=event.revision;}
  if(event.type==='ended'){freezeFilm();detach();revision=event.revision;phase('ended','Where does that take your curiosity?');}
  if(event.type==='error'){freezeFilm();detach();ending=true;phase('error',event.message);}
}
// The media clock, not generation-complete messages, decides what the viewer has heard.
function presented(_now, metadata) {
  if(peer && !video.paused && video.readyState>=2 && !ending){
    if(startTime===null){displayedTitle=nextTitle;$('title').textContent=displayedTitle;startTime=metadata.mediaTime;metrics.push({type:'presented',at:performance.now()});}
    document.body.dataset.hasFilm='true';freeze.hidden=true;phase('playing', 'Hold the pink button to ask something.');
    const elapsed=Math.max(0,metadata.mediaTime-startTime), progress=Math.min(100,elapsed/duration*100);
    $('progress').style.setProperty('--progress',`${progress}%`);
    $('progress').firstElementChild.style.width=`${progress}%`;
    $('progress').setAttribute('aria-valuenow',Math.round(progress));
    if(duration && elapsed>=duration){ending=true;freezeFilm();send({type:'finished',revision});phase('ended','Where does that take your curiosity?');}
  }
  video.requestVideoFrameCallback(presented);
}
if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(presented);
else video.addEventListener('timeupdate',()=>{if(!video.paused){document.body.dataset.hasFilm='true';freeze.hidden=true;phase('playing', 'Hold the pink button to ask something.');if(startTime===null)startTime=video.currentTime;if(video.currentTime-startTime>=duration&&!ending){ending=true;freezeFilm();send({type:'finished',revision});}}});
$('question').addEventListener('submit',e=>{e.preventDefault();ask($('ask').value);});
document.querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>ask(button.dataset.question)));
$('pause').onclick=interrupt;
$('sound').onclick=()=>{muted=!muted;video.muted=muted;$('sound').textContent=muted?'Sound off':'Sound on';$('sound').setAttribute('aria-label',muted?'Unmute sound':'Mute sound');};
$('resume').onclick=async()=>{video.muted=muted;await video.play();$('resume').hidden=true;};
$('access').addEventListener('close',async()=>{try{await connect($('code').value);$('code').value='';phase('idle','');}catch(error){$('access-error').textContent=error.message;}});
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
$('talk').addEventListener('pointerdown',e=>{e.preventDefault();$('talk').setPointerCapture(e.pointerId);startRecording();});
['pointerup','pointercancel','lostpointercapture'].forEach(kind=>$('talk').addEventListener(kind,stopRecording));
$('talk').addEventListener('keydown',e=>{if([' ','Enter'].includes(e.key)&&!e.repeat){e.preventDefault();startRecording();}});
$('talk').addEventListener('keyup',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();stopRecording();}});
window.addEventListener('pagehide',()=>{send({type:'interrupt'});socket?.close();peer?.close();microphone?.getTracks().forEach(t=>t.stop());});
document.addEventListener('visibilitychange',()=>{if(document.hidden){stopRecording();if(peer)interrupt();}});
window.addEventListener('blur',stopRecording);
