// Wires the toolbar icon to open the panel UI.
async function init() {
  // Ensure SDK is ready
  await miro.board.ui.on('icon:click', async () => {
    await miro.board.ui.openPanel({ url: 'panel.html' });
  });
}
init();
