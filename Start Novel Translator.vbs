Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("Wscript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = folder
' Keep the installer window visible so ready-checks can be read.
WshShell.Run "cmd /c """ & folder & "\Start Novel Translator.bat""", 1, False
