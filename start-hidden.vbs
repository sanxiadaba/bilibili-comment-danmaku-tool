' Start without a console window. Double-click: runs the service in the background and opens the browser.
' Stop: end pythonw.exe in Task Manager.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root

If Not fso.FileExists(root & "\dist\index.html") Then
  MsgBox "The frontend is not built yet. Double-click start.cmd once first.", 48, "Bilibili comment/danmaku tool"
  WScript.Quit 1
End If

shell.Run "pythonw.exe backend\desktop_entry.py", 0, False