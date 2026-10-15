GaussianReadPro — Windows portable build

Run GaussianReadPro.exe to start the app. Keep the entire GaussianReadPro folder
together; the executable uses bundled Qt, WebEngine, chart, theme, locale, and
Matplotlib resources from the _internal folder.

This build was produced on Windows 11 x64 with Python 3.12.14. It is a portable
onedir folder, not a signed installer. Copy or extract the complete folder to a
writable location. Windows SmartScreen may show its normal warning because this
local build is not code-signed.

If the app crashes on this particular host under the default CPU scheduler,
close it and try Launch-GaussianReadPro-compat.cmd. That script limits only this
app and its child processes to the repository's tested process affinity mask;
it does not change Windows or BIOS settings. The underlying G4 default-scheduler
issue is still under investigation.

The app reads Gaussian logs locally. Do not remove _internal. To move saved
preferences or recovery files between machines, use the app's project save/open
commands; per-user recent-project settings are stored by Windows in AppData.
