' Lance Beheread sans fenetre de console.
' Double-cliquer sur ce fichier suffit. Peut aussi etre epingle
' au Bureau ou a la barre des taches (clic droit > Envoyer vers > Bureau).

Option Explicit
Dim objShell, objFSO, strPath, exitCode

Set objFSO = CreateObject("Scripting.FileSystemObject")
strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)

Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = strPath

On Error Resume Next
exitCode = objShell.Run("pythonw.exe main.py", 1, True)
If Err.Number <> 0 Or exitCode <> 0 Then
    MsgBox "Impossible de lancer Beheread." & vbCrLf & vbCrLf & _
           "Verifiez que Python est installe et ajoute au PATH," & vbCrLf & _
           "et que les dependances sont installees (pip install -r requirements.txt)." & vbCrLf & vbCrLf & _
           "Voir le fichier README.md pour l'installation complete.", _
           vbCritical, "Beheread"
End If
