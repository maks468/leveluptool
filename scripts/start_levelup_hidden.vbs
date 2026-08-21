' Starts the LevelUp CRM backend (which also serves the built frontend)
' with no visible console window. Placed in shell:startup via a copy so it
' runs at Windows logon. The app is then available at http://localhost:8322.
Set shell = CreateObject("WScript.Shell")
shell.Run """C:\LevelUp Tool\leveluptool\scripts\run_backend.cmd""", 0, False
