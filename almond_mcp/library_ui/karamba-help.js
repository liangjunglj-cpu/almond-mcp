// Local, keyboard-accessible explainers. Opening help never edits analysis inputs.
const topics = [
  {target:'.analysis-page h1', title:'Start here', steps:[
    'Check that Karamba is installed and available in Rhino.',
    'Select structural axes, surfaces or meshes in Rhino, then choose Use Rhino selection.',
    'Review materials, loads, supports and sections. Run Karamba analysis.',
    'Read the warnings with the results. Recapture after editing Rhino geometry; rerun after changing inputs.'
  ]},
  {target:'.engine-line', title:'Check the engine', text:'Check engine asks Rhino whether Karamba is available. Install and license Karamba separately. Browsing this panel does not require it, but running an analysis does. An unavailable engine will not be replaced with an estimated result.'},
  {target:'.analysis-step:nth-child(1) h2', title:'Choose structural geometry', text:'Select the centreline curves of members, or structural shell surfaces/meshes. Include Rhino point objects where supports should be placed. Then press Use Rhino selection. Library furniture and decorative Meshy objects are visual assets; their meshes are not automatically valid structural models.', steps:['Check Rhino document units and connectivity.','Recapture whenever the selected geometry changes.']},
  {target:'#analysis-settings h2', title:'Set up the analysis', text:'Choose the intended structure type and material, then enter the total downward load in kN. This is a total load, not a load per square metre. Almond shares it between free nodes. Self-weight is added separately when enabled.', steps:['Support locations: use selected points, or let Almond find the lowest nodes. Choose Require selected points when you want explicit control.','Fixed restrains translation and rotation. Pinned restrains translation only.','Check section assumptions. A CHS override specifies circular hollow section diameter and wall thickness in mm. Shells use the stated thickness assumption.'], diagram:'supports'},
  {target:'.diagram-step h2', title:'Read the diagram', text:'Use the view selector to change projection. The checkboxes show or hide members, supports, loads and utilization. They only change the display; they do not change the analysis.', steps:['Before capturing geometry, the diagram is an illustrative frame.','Load arrows indicate direction, not force magnitude.','Utilization colours appear only when the solver supplies results. They show the maximum mapped value for each source member. No deformed shape is shown.'], diagram:'legend'},
  {target:'#analysis-results h2', title:'Interpret results', text:'Deflection is displacement in mm. Utilization is demand relative to the configured capacity check: 100% is the threshold used here. The L/250 deflection comparison is an indicative screen, not a complete project-specific design check.', steps:['Read warnings and missing evidence before interpreting a pass or fail.','Select worst members highlights the corresponding Rhino objects.','Save analysis JSON records the settings and result snapshot. Changing inputs makes that snapshot stale until you rerun.']}
];
const diagrams = {
  supports:'<svg viewBox="0 0 280 75" role="img" aria-label="Fixed support restrains translation and rotation; pinned support restrains translation"><path d="M55 8v34M205 8v34" stroke="var(--diagram-member,currentColor)" stroke-width="4"/><path d="M44 43h22v8H44Z" fill="var(--diagram-support,#237963)"/><path d="m205 43-10 12h20Z" fill="none" stroke="var(--diagram-support,#237963)" stroke-width="2"/><text x="55" y="71" text-anchor="middle">Fixed</text><text x="205" y="71" text-anchor="middle">Pinned</text></svg>',
  legend:'<svg viewBox="0 0 280 60" role="img" aria-label="Member line, green support, downward load arrow"><path d="M15 22h48" stroke="var(--diagram-member,currentColor)" stroke-width="4"/><path d="M130 17h22v9h-22Z" fill="var(--diagram-support,#237963)"/><path d="M239 4v28m-5-6 5 6 5-6" fill="none" stroke="var(--diagram-load,#c23220)" stroke-width="2"/><text x="39" y="54" text-anchor="middle">Member</text><text x="141" y="54" text-anchor="middle">Support</text><text x="239" y="54" text-anchor="middle">Load</text></svg>'
};
let openButton;
topics.forEach((topic,index)=>{
  const target=document.querySelector(topic.target);
  if(!target)return;
  const button=document.createElement('button');
  button.type='button';button.className='help-button';button.textContent='?';
  button.setAttribute('aria-label','Help: '+topic.title);
  button.setAttribute('title',topic.title);button.setAttribute('aria-expanded','false');
  const panel=document.createElement('aside');panel.className='help-panel';panel.id='karamba-help-'+index;panel.hidden=true;
  button.setAttribute('aria-controls',panel.id);
  const heading=document.createElement('h3');heading.textContent=topic.title;panel.append(heading);
  if(topic.text){const p=document.createElement('p');p.textContent=topic.text;panel.append(p);}
  if(topic.diagram){const figure=document.createElement('div');figure.innerHTML=diagrams[topic.diagram];panel.append(figure);}
  if(topic.steps){const list=document.createElement('ol');topic.steps.forEach(step=>{const li=document.createElement('li');li.textContent=step;list.append(li);});panel.append(list);}
  const close=()=>{panel.hidden=true;button.setAttribute('aria-expanded','false');if(openButton===button)openButton=null;};
  button.addEventListener('click',()=>{
    const expand=panel.hidden;
    if(openButton && openButton!==button)openButton.click();
    panel.hidden=!expand;button.setAttribute('aria-expanded',String(expand));openButton=expand?button:null;
  });
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){close();button.focus();event.stopPropagation();}});
  button.addEventListener('keydown',event=>{if(event.key==='Escape'){close();event.stopPropagation();}});
  target.classList.add('has-help');target.append(button);target.after(panel);
});
