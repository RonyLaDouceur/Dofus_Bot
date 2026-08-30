Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = scriptDir & "\.venv\Scripts\pythonw.exe"
python = scriptDir & "\.venv\Scripts\python.exe"
app = scriptDir & "\aggro_ui.py"

If fso.FileExists(pythonw) Then
    shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & app & Chr(34), 0, False
ElseIf fso.FileExists(python) Then
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & app & Chr(34), 0, False
Else
    shell.Run "python " & Chr(34) & app & Chr(34), 0, False
End If