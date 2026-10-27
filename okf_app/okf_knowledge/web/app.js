const conversation = document.querySelector('#conversation');
const question = document.querySelector('#question');
const form = document.querySelector('#ask-form');
const ask = document.querySelector('#ask');
const dialog = document.querySelector('#source-dialog');
let pending = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function getJSON(url) {
  const response = await fetch(url, {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The local knowledge bundle is unavailable.');
  return data;
}

async function showSource(name) {
  try {
    const data = await getJSON('/api/document?name=' + encodeURIComponent(name));
    document.querySelector('#source-title').textContent = data.title;
    document.querySelector('#source-path').textContent = data.document;
    document.querySelector('#source-body').innerHTML = data.body_html;
    if (!dialog.open) dialog.showModal();
  } catch (error) {
    const message = element('p', 'error', error.message);
    conversation.append(message);
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (pending || !question.value.trim()) return;
  const submitted = question.value.trim();
  document.querySelector('#welcome')?.remove();
  const turn = element('article', 'turn');
  turn.append(element('div', 'question-label', 'YOUR QUESTION'));
  turn.append(element('p', 'user-question', submitted));
  const answer = element('div', 'answer');
  answer.append(element('p', 'pending', 'Reading the OKF bundle…'));
  turn.append(answer);
  conversation.append(turn);
  pending = true;
  ask.disabled = true;
  document.querySelectorAll('.suggestion').forEach(button => button.disabled = true);
  try {
    const data = await getJSON('/api/ask?question=' + encodeURIComponent(submitted));
    answer.replaceChildren();
    const label = element('div', 'answer-label');
    label.append(element('span', 'dot'), document.createTextNode(data.supported ? 'OKF-grounded answer' : 'Outside the knowledge bundle'));
    const body = element('div', 'markdown');
    body.innerHTML = data.answer_html;
    answer.append(label, body);
    if (data.document) {
      const source = element('div', 'source');
      const top = element('div', 'source-top', 'Source concept');
      const button = element('button', 'source-button', data.document);
      button.type = 'button';
      button.addEventListener('click', () => showSource(data.document));
      top.append(button);
      source.append(top, element('small', '', data.title + (data.section ? ' / ' + data.section : '')));
      answer.append(source);
    }
    question.value = '';
  } catch (error) {
    answer.replaceChildren(element('p', 'error', error.message));
  } finally {
    pending = false;
    ask.disabled = false;
    document.querySelectorAll('.suggestion').forEach(button => button.disabled = false);
    conversation.scrollTop = turn.offsetTop - conversation.offsetTop;
  }
});

question.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); form.requestSubmit();}
});
document.querySelectorAll('.suggestion').forEach(button => {
  button.addEventListener('click', () => {question.value = button.textContent; form.requestSubmit();});
});
document.querySelector('#reset').addEventListener('click', () => {
  if (pending) return;
  conversation.replaceChildren(element('p', 'pending', 'Choose a question to begin a fresh demonstration.'));
  question.value = '';
  question.focus();
});
document.querySelector('#close-source').addEventListener('click', () => dialog.close());
document.addEventListener('click', event => {
  const link = event.target.closest('a');
  if (link && /^[a-z0-9-]+\.md$/.test(link.getAttribute('href') || '')) {
    event.preventDefault(); showSource(link.getAttribute('href'));
  }
});
getJSON('/api/concepts').then(concepts => {
  const list = document.querySelector('#concepts');
  concepts.forEach(concept => {
    const button = element('button', 'concept');
    button.type = 'button';
    button.append(element('span', '', concept.title), element('span', '', '↗'));
    button.addEventListener('click', () => showSource(concept.document));
    list.append(button);
  });
}).catch(error => document.querySelector('#concepts').append(element('p', 'error', error.message)));
