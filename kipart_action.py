import os
import json
import threading

import wx
import wx.adv
import wx.lib.agw.persist.persistencemanager as PM
import pcbnew


if __name__ == '__main__':
    import kipart_gui
    import KiPartClient
    from KiPartClient.About import (
        CONTACT, GPL_URL, LICENSE_PARAGRAPHS, SERVER_LABELS, client_version, version_fields,
    )
else:
    from . import kipart_gui
    from . import KiPartClient
    from .KiPartClient.About import (
        CONTACT, GPL_URL, LICENSE_PARAGRAPHS, SERVER_LABELS, client_version, version_fields,
    )

def ensure_dialog_fits(dialog, prefer=None):
    """Grow a dialog so its sizer contents stay fully visible.

    Sizes chosen on Windows are too small on GTK: the client area clips the
    last rows and the left edge of group boxes. Control sizes are only final
    after the window is shown, so the correction runs then.
    """
    state = {"done": False}

    def apply():
        sizer = dialog.GetSizer()
        if sizer is None:
            return
        dialog.Layout()
        needed = sizer.CalcMin()
        if wx.Platform == "__WXGTK__":
            needed = wx.Size(needed.width + 12, needed.height + 12)
        client = dialog.GetClientSize()
        width = max(client.width, needed.width)
        height = max(client.height, needed.height)
        if (width, height) != (client.width, client.height):
            dialog.SetClientSize(wx.Size(width, height))
            dialog.Layout()
        if prefer:
            size = dialog.GetSize()
            pref_w, pref_h = prefer
            grown = wx.Size(
                size.width if pref_w < 0 else max(size.width, pref_w),
                size.height if pref_h < 0 else max(size.height, pref_h),
            )
            if grown != size:
                dialog.SetSize(grown)
        dialog.SetMinSize(dialog.GetSize())
        dialog.Centre(wx.BOTH)

    def on_show(event):
        event.Skip()
        if event.IsShown() and not state["done"]:
            state["done"] = True
            wx.CallAfter(apply)

    dialog.Bind(wx.EVT_SHOW, on_show)


class KiPart(pcbnew.ActionPlugin):
    def defaults(self):
        self.version = ""
        self.metadata_file = os.path.join(os.path.dirname(__file__), 'metadata.json')
        with open(self.metadata_file, 'r') as f:
            data = json.load(f)
            self.version = data['versions'][0]['version']

        self.name = data['name']
        self.category = "Managing part data"
        self.description = data['description']
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'kipart_24x24.png')

    def Run(self):
        self.frame = wx.FindWindowByName("PcbFrame")
        dlg = KiPartDialog(self.frame)
        dlg.SetIcon( wx.Icon(self.icon_file_name) )
        dlg.SetTitle( self.name+" v"+self.version )
        dlg.Show()


class KiPartDialog ( kipart_gui.KiPartGUI ):
    def __init__(self, parent):
        kipart_gui.KiPartGUI.__init__(self, parent)

        self.KICAD_VERSION = int(pcbnew.Version().split(".")[0])
        self._settings = KiPartClient.Settings(self)        

        dir_path = os.path.dirname(os.path.realpath(__file__))

        # set images with correct path (doesn't work when set by wxFormBuilder)
        self.btAddLib.SetBitmap( wx.Bitmap( dir_path + "/resources/icon_add.png", wx.BITMAP_TYPE_ANY ) )
        self.btDeleteLib.SetBitmap( wx.Bitmap( dir_path + "/resources/icon_delete.png", wx.BITMAP_TYPE_ANY ) )
        self.btEditLib.SetBitmap( wx.Bitmap( dir_path + "/resources/icon_edit.png", wx.BITMAP_TYPE_ANY ) )
        self.headerImage.SetBitmap( wx.Bitmap( dir_path + "/resources/icon_sync.png", wx.BITMAP_TYPE_ANY ) )

        # reset GUI elements
        self.btCheck.Enable(False)
        self.btSync.Enable(False)
        self.btDeleteLib.Enable(False)
        self.btEditLib.Enable(False)
        self._job_running = False
        self._force_download = False

        self.btForceDownload = wx.Button(self, wx.ID_ANY, "Forced Download", wx.DefaultPosition, wx.Size(150, 50), 0)
        self.btForceDownload.Enable(False)
        self.btForceDownload.SetToolTip("Replace the local library with the current online state. Nothing is uploaded.")
        check_sizer = self.btCheck.GetContainingSizer()
        if check_sizer is not None:
            check_sizer.Insert(1, self.btForceDownload, 0, wx.ALL, 5)
        self.Bind(wx.EVT_BUTTON, self.btForceDownloadOnLeftUp, self.btForceDownload)

        header_sizer = self.lTitleText.GetContainingSizer()
        self.activityIndicator = wx.ActivityIndicator(self, size=wx.Size(28, 28))
        self.activityIndicator.Hide()
        self.activityIndicator.SetToolTip("Check or sync in progress")
        header_sizer.Insert(2, self.activityIndicator, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 8)

        sidebar = self.lbLibList.GetContainingSizer()
        self.btInfo = wx.Button(self, wx.ID_ANY, "Info")
        self.btInfo.SetToolTip("Version and license")
        sidebar.Add(self.btInfo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.Bind(wx.EVT_BUTTON, self._onInfo, self.btInfo)
        self.Layout()


    def _onInfo(self, event):
        config = None
        selected = self.lbLibList.GetSelection()
        if selected >= 0 and selected < len(getattr(self, "_libList", []) or []):
            config = self._libList[selected]
        dialog = InfoDialog(self, config)
        dialog.ShowModal()
        dialog.Destroy()

    def KiPartGUIOnShow( self, event ):
        self.updateLibraryList(0)

    def updateLibraryList(self, index = 0):
        self._libList = self._settings.get_library_list()
        libStringList = []
        for library in self._libList:
            libStringList.append(library['name'])

        self.lbLibList.Clear()
        if len(libStringList) > 0:
            self.lbLibList.InsertItems(libStringList, 0)    

        # select first library by default
        if len(self._libList) > 0:
            if index < len(self._libList):
                self._settings.set_current_index(index)
                self.lbLibList.SetSelection(index)
                self.lTitleText.SetLabel("Sync " + self._libList[index]['name'])
            else:
                self._settings.set_current_index(0)
                self.lbLibList.SetSelection(0)
                self.lTitleText.SetLabel("Sync " + self._libList[0]['name'])

            self.btSync.Enable(False)
            self.btDeleteLib.Enable(True)
            self.btEditLib.Enable(True)
            self._enableCheckButtons()
        else:
            self.lTitleText.SetLabel("Sync Library")
            self.btCheck.Enable(False)
            self.btForceDownload.Enable(False)
            self.btSync.Enable(False)
            self.btDeleteLib.Enable(False)
            self.btEditLib.Enable(False)
            
        

    def lbLibListOnListBox( self, event ):
        selID = self.lbLibList.GetSelection()
        if selID >= 0:
            self._settings.set_current_index(selID)
            self.lTitleText.SetLabel("Sync " + self._libList[selID]['name'])
            self.btSync.Enable(False)
            self._enableCheckButtons()
        else:
            self.lTitleText.SetLabel("Sync Library")
            self.btCheck.Enable(False)
            self.btForceDownload.Enable(False)
            self.btSync.Enable(False)
        self.lCntNew.SetLabel("-")
        self.lCntChanged.SetLabel("-")
        self.lCntDeleted.SetLabel("-")
        self.lCntConflict.SetLabel("-")
        self.lCntUnchanged.SetLabel("-")



    def btAddLibOnLeftUp( self, event ):
        with KiPartSettingsDialog(self) as dlg:
            dlg.SetTitle("Add Library")
            setData = self._accepted_library_settings(dlg)
        if setData is None:
            return

        setData['api_url'] = setData['api_url'].rstrip('/')
        self._settings.add_library_data(setData)
        self.updateLibraryList(len(self._libList))
        self._updateKiCadSettings(
            lambda: KiPartClient.addKiCadEnvVars(setData['path_key'], setData['output_path'])
        )


    def btDeleteLibOnLeftUp( self, event ):
        if wx.MessageDialog(self, "Are you sure you want to delete the library?", "Delete Library", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_EXCLAMATION).ShowModal() == wx.ID_YES:

            curSelection = self.lbLibList.GetSelection()
            cur_data = self._libList[curSelection]

            # remove the library's tables from KiCad's global library tables
            KiPartClient.unregisterLibraryTables(cur_data['path_key'])

            # Update KiCad environment variables
            KiPartClient.removeKiCadEnvVars(cur_data['path_key'])

            self._settings.remove_current_library()
            self.updateLibraryList(0)


    def btEditLibOnLeftUp( self, event ):
        curSelection = self.lbLibList.GetSelection()
        with KiPartSettingsDialog(self, self._libList[curSelection]) as dlg:
            dlg.SetTitle("Edit Library Settings")
            setData = self._accepted_library_settings(dlg)
        if setData is None:
            return

        setData['api_url'] = setData['api_url'].rstrip('/')
        cur_data = self._libList[curSelection]
        self._settings.set_current_library_data(setData)
        self.updateLibraryList(curSelection)

        def update_kicad():
            if cur_data['path_key'] != setData['path_key']:
                KiPartClient.renameKiCadEnvVars(cur_data['path_key'], setData['path_key'])
            if cur_data['output_path'] != '' and cur_data['output_path'] != setData['output_path']:
                KiPartClient.updateKiCadEnvVars(setData['path_key'], setData['output_path'])
            KiPartClient.updateLibraryTables(cur_data['name'], cur_data['path_key'], setData['name'], setData['path_key'], setData['output_path'])
            KiPartClient.CreateLibraryFiles.refreshHttpLibraryFile(setData)

        self._updateKiCadSettings(update_kicad)

    def _accepted_library_settings(self, dlg):
        """Return the field values when Save closed the dialog.

        On GTK, wx.ID_SAVE is a stock button. It ends the modal dialog itself
        and the return code from ShowModal() is not wx.APPLY, so checking only
        that code drops the new library without an error.
        """
        code = dlg.ShowModal()
        if not dlg.WasAccepted() and code == wx.ID_SAVE:
            dlg.CaptureSettings()
        if not dlg.WasAccepted():
            return None
        return dlg.GetSettingsData()

    def _updateKiCadSettings(self, action):
        try:
            action()
        except Exception as exc:
            wx.MessageBox(
                "The library was saved, but KiCad's path variables could not be updated.\n\n" + str(exc),
                "KiCad settings",
                wx.OK | wx.ICON_WARNING,
                self,
            )
                

    def _enableCheckButtons(self):
        enabled = (not self._job_running) and self.lbLibList.GetSelection() >= 0
        self.btCheck.Enable(enabled)
        self.btForceDownload.Enable(enabled)

    def _applyBusy(self, busy):
        if busy:
            self.activityIndicator.Show()
            self.activityIndicator.Start()
        else:
            self.activityIndicator.Stop()
            self.activityIndicator.Hide()
        self.Layout()

    def _setBusy(self, busy):
        if wx.IsMainThread():
            self._applyBusy(busy)
        else:
            wx.CallAfter(self._applyBusy, busy)

    def _ui(self, func):
        """Run a dialog update on the UI thread.

        Check and sync call back from a worker thread. Touching wx widgets
        from that thread deadlocks GTK and then crashes KiCad.
        """
        def run():
            try:
                if self.IsBeingDeleted():
                    return
            except RuntimeError:
                return
            try:
                func()
            except RuntimeError:
                return
        if wx.IsMainThread():
            run()
        else:
            wx.CallAfter(run)

    def _count_snapshot(self, data):
        data = data or {}
        return {
            'cntNew': data.get('cntNew') or 0,
            'cntChanged': data.get('cntChanged') or 0,
            'cntDeleted': data.get('cntDeleted') or 0,
            'cntConflict': data.get('cntConflict') or 0,
            'cntUnchanged': data.get('cntUnchanged') or 0,
        }

    def _apply_counts(self, counts):
        self.lCntNew.SetLabel(str(counts['cntNew']) if counts['cntNew'] > 0 else "-")
        self.lCntChanged.SetLabel(str(counts['cntChanged']) if counts['cntChanged'] > 0 else "-")
        self.lCntDeleted.SetLabel(str(counts['cntDeleted']) if counts['cntDeleted'] > 0 else "-")
        self.lCntConflict.SetLabel(str(counts['cntConflict']) if counts['cntConflict'] > 0 else "-")
        self.lCntUnchanged.SetLabel(str(counts['cntUnchanged']) if counts['cntUnchanged'] > 0 else "-")

    def _finishJob(self):
        if not wx.IsMainThread():
            wx.CallAfter(self._finishJob)
            return
        self._job_running = False
        self._enableCheckButtons()
        self._setBusy(False)

    def _resetCounts(self):
        self.lCntNew.SetLabel("-")
        self.lCntChanged.SetLabel("-")
        self.lCntDeleted.SetLabel("-")
        self.lCntConflict.SetLabel("-")
        self.lCntUnchanged.SetLabel("-")

    def _prepareLibraryPath(self, wipe_without_prompt):
        config = self._settings.get_current_library_data()
        if KiPartClient.CreateLibraryFiles.checkIfLibraryPathExists(config):
            KiPartClient.CreateLibraryFiles.refreshHttpLibraryFile(config)
            return True
        if not wipe_without_prompt:
            if wx.MessageDialog(self, "Seems to be the first download. This will delete the selected output dir and do a full sync.", "First Synchronization", wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT | wx.ICON_EXCLAMATION).ShowModal() != wx.ID_OK:
                return False
        retVal = KiPartClient.CreateLibraryFiles.createLibraryFiles(config)
        if retVal != KiPartClient.Misc.ReturnCode.OK:
            if retVal == KiPartClient.Misc.ReturnCode.NoConnection:
                wx.MessageDialog(self, "Could not connect to API.", "Connection Error", wx.OK | wx.OK_DEFAULT | wx.ICON_ERROR).ShowModal()
            elif retVal == KiPartClient.Misc.ReturnCode.FileWriteError:
                wx.MessageDialog(self, "Could not write target path.", "Writing Error", wx.OK | wx.OK_DEFAULT | wx.ICON_ERROR).ShowModal()
            else:
                wx.MessageDialog(self, "Unknown error while creating library files", "Unknown Error", wx.OK | wx.OK_DEFAULT | wx.ICON_ERROR).ShowModal()
            return False
        return True

    def _startLibraryCheck(self, force_download):
        self._resetCounts()
        if not self._prepareLibraryPath(wipe_without_prompt=force_download):
            return
        self._force_download = force_download
        self._job_running = True
        self.btSync.Enable(False)
        self._enableCheckButtons()
        self._setBusy(True)
        self.gProgress.SetRange(7)
        self.gProgress.SetValue(0)
        self.tProtocol.Clear()
        if force_download:
            self.tProtocol.AppendText("Forced download: comparing with the online library\n")
        thread = threading.Thread(
            target=KiPartClient.checkLibrary,
            args=(self._settings.get_current_library_data(), self.__checkLibraryProgressCallback, self.__checkLibraryFinishedCallback),
            kwargs={"force_remote": force_download},
        )
        thread.start()

    def btCheckOnLeftUp( self, event ):
        self._startLibraryCheck(False)
        event.Skip()

    def btForceDownloadOnLeftUp(self, event):
        if wx.MessageDialog(
            self,
            "Forced Download replaces the local library with the current online state.\n"
            "Local changes are discarded and local-only files are removed. Nothing is uploaded.",
            "Forced Download",
            wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT | wx.ICON_EXCLAMATION,
        ).ShowModal() != wx.ID_OK:
            return
        self._startLibraryCheck(True)
        event.Skip()


    def btSyncOnLeftUp( self, event ):
        # start checking function in a non blocking way
        config_data = self._settings.get_current_library_data()

        self._job_running = True
        self.btSync.Enable(False)
        self._enableCheckButtons()
        self._setBusy(True)

        self.gProgress.SetRange(7)
        self.gProgress.SetValue(0)
        self.tProtocol.Clear()

        def commit_message_provider(changes_summary):
            """Marshal commit dialog onto the GUI thread; return the message or None."""
            box = {'result': None}
            done = threading.Event()

            def show_dialog():
                try:
                    with CommitMessageDialog(self, changes_summary) as dlg:
                        if dlg.ShowModal() == wx.ID_OK:
                            box['result'] = dlg.GetResult()
                finally:
                    done.set()

            wx.CallAfter(show_dialog)
            done.wait()
            return box['result']

        thread = threading.Thread(
            target=KiPartClient.syncLibrary,
            args=(config_data, self._check_data, self.__syncLibraryProgressCallback, self.__syncLibraryFinishedCallback, self.__syncSubProgressCallback),
            kwargs={'commit_message_provider': commit_message_provider},
        )
        thread.start()

        event.Skip()

    
    def __checkLibraryProgressCallback(self, check_data, message, percentage):
        self._check_data = check_data
        counts = self._count_snapshot(check_data)
        def apply(counts=counts, message=message, percentage=percentage):
            self._apply_counts(counts)
            self.tProtocol.AppendText(message + "\n")
            self.gProgress.SetValue(percentage)
        self._ui(apply)


    def __checkLibraryFinishedCallback(self, check_data, message):
        self._check_data = check_data
        counts = self._count_snapshot(check_data)
        def paint(counts=counts, message=message):
            self._apply_counts(counts)
            self.tProtocol.AppendText(message + "\n\n")
            self.gProgress.SetValue(0)
        self._ui(paint)
        if self._force_download:
            self._force_download = False
            failed = (message or "").startswith("No connection") or (message or "").startswith("Connection") or "API version" in (message or "")
            if failed:
                self._finishJob()
                return
            KiPartClient.mark_take_server(check_data)
            if not KiPartClient.iter_change_rows(check_data):
                self._ui(lambda: self.tProtocol.AppendText("Forced download: local library already matches the server\n"))
                self._finishJob()
                return
            self._ui(lambda: self.tProtocol.AppendText("Forced download: resetting local files to the online state\n"))
            KiPartClient.syncLibrary(
                self._settings.get_current_library_data(),
                check_data,
                self.__syncLibraryProgressCallback,
                self.__syncLibraryFinishedCallback,
                self.__syncSubProgressCallback,
            )
            return
        wx.CallAfter(self._afterCheck, check_data)


    def __syncLibraryProgressCallback(self, sync_data, message, percentage):
        self._sync_data = sync_data
        counts = self._count_snapshot(sync_data)
        def apply(counts=counts, message=message, percentage=percentage):
            self._apply_counts(counts)
            self.tProtocol.AppendText(message + "\n")
            self.gProgress.SetValue(percentage)
        self._ui(apply)


    def __syncSubProgressCallback(self, is_start, is_end, message, percentage):
        def apply(is_start=is_start, is_end=is_end, message=message, percentage=percentage):
            if is_start:
                self.gSubProgress.SetValue(0)
                self.gSubProgress.SetRange(percentage)
            elif is_end:
                self.gSubProgress.SetValue(0)
            else:
                self.gSubProgress.SetValue(percentage)
                self.tProtocol.AppendText("\t" + message + "\n")
        self._ui(apply)


    def __syncLibraryFinishedCallback(self, sync_data, message):
        self._sync_data = sync_data
        counts = self._count_snapshot(sync_data)
        def apply(counts=counts, message=message):
            self._apply_counts(counts)
            self.tProtocol.AppendText(message + "\n\n")
            self.gProgress.SetValue(0)
            self.btSync.Enable(False)
            self._finishJob()
            if message and "still in use" in message.lower():
                wx.MessageBox(message, "Delete blocked", wx.OK | wx.ICON_ERROR, self)
        self._ui(apply)

    def _afterCheck(self, check_data):
        self._finishJob()
        self._presentChangeReview(check_data)

    def _presentChangeReview(self, check_data):
        rows = KiPartClient.iter_change_rows(check_data)
        if not rows:
            self.btSync.Enable(False)
            return
        dialog = ChangeReviewDialog(self, rows)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                self.btSync.Enable(False)
                self.tProtocol.AppendText("Review cancelled\n")
                return
            KiPartClient.write_decisions(rows)
        finally:
            dialog.Destroy()
        counts = {"apply": 0, "ignore": 0, "revert": 0}
        for row in rows:
            counts[row.decision] = counts.get(row.decision, 0) + 1
            self.tProtocol.AppendText(f"\t{row.decision}: {row.category} {row.path} ({row.change})\n")
        self.tProtocol.AppendText(
            f"Review: {counts['apply']} apply, {counts['ignore']} ignore, {counts['revert']} revert\n"
        )
        self.btSync.Enable(counts["apply"] + counts["revert"] > 0)



class InfoDialog(wx.Dialog):
    """About box: client and server versions, plus the GPL notice."""

    def __init__(self, parent, library_config):
        wx.Dialog.__init__(
            self, parent, title="Info",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._closed = False
        self._config = library_config if library_config and library_config.get("api_url") else None
        self._kicad = ""
        try:
            self._kicad = pcbnew.Version()
        except Exception:
            self._kicad = ""
        self.Bind(wx.EVT_CLOSE, self._on_close)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self._build_versions(), 0, wx.ALL | wx.EXPAND, 8)
        root.Add(self._build_license(), 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        root.Add(self.CreateButtonSizer(wx.OK), 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizer(root)
        self.SetSize((560, 640))
        ensure_dialog_fits(self, prefer=(560, 640))

        if self._config is not None:
            threading.Thread(target=self._load_server, daemon=True).start()

    def _on_close(self, event):
        self._closed = True
        event.Skip()

    def _build_versions(self):
        box = wx.StaticBoxSizer(wx.StaticBox(self, label="Version"), wx.VERTICAL)
        intro = wx.StaticText(
            self,
            label="Release of this client, the KiCad version, and the server of the selected library.",
        )
        intro.Wrap(500)
        box.Add(intro, 0, wx.ALL | wx.EXPAND, 8)

        grid = wx.FlexGridSizer(0, 2, 6, 16)
        grid.AddGrowableCol(1)
        self._values = {}
        pending = self._config is not None
        for label, value in version_fields(client_version(), self._kicad, None):
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            shown = "Loading…" if pending and label in SERVER_LABELS else value
            text = wx.StaticText(self, label=shown)
            font = text.GetFont()
            font.SetFamily(wx.FONTFAMILY_TELETYPE)
            text.SetFont(font)
            self._values[label] = text
            grid.Add(text, 1, wx.ALIGN_CENTER_VERTICAL | wx.EXPAND)
        box.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        note = ""
        if self._config is None:
            note = "Select a library to read the server version."
        self._server_note = wx.StaticText(self, label=note)
        self._server_note.Wrap(500)
        box.Add(self._server_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        return box

    def _build_license(self):
        box = wx.StaticBoxSizer(wx.StaticBox(self, label="License"), wx.VERTICAL)
        for paragraph in LICENSE_PARAGRAPHS:
            text = wx.StaticText(self, label=paragraph)
            text.Wrap(500)
            box.Add(text, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)
        box.Add(wx.adv.HyperlinkCtrl(self, label=GPL_URL, url=GPL_URL), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        heading = wx.StaticText(self, label="Contact")
        heading.SetFont(heading.GetFont().Bold())
        box.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        for label, url in CONTACT:
            if url:
                box.Add(wx.adv.HyperlinkCtrl(self, label=label, url=url), 0, wx.LEFT | wx.RIGHT, 8)
            else:
                box.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT, 8)
        box.Add((0, 8), 0)
        return box

    def _load_server(self):
        info = None
        error = ""
        try:
            info = KiPartClient.RestAPI(self._config).info()
        except Exception:
            error = "Could not read the server version."
        wx.CallAfter(self._apply_server, info, error)

    def _apply_server(self, info, error):
        if self._closed:
            return
        for label, value in version_fields(client_version(), self._kicad, info):
            if label in SERVER_LABELS:
                self._values[label].SetLabel(value)
        self._server_note.SetLabel(error)
        self._server_note.Wrap(500)
        self.Layout()


class KiPartSettingsDialog ( kipart_gui.SettingsDialog ):
    def __init__(self, parent, data=None):
        kipart_gui.SettingsDialog.__init__(self, parent)
        self._accepted = False
        # Enter should activate Save. The button keeps wx.ID_SAVE so the
        # standard button sizer lays it out; on GTK that stock id also closes
        # the dialog and can replace the EndModal() code.
        self.SetAffirmativeId(wx.ID_SAVE)

        for ctrl in (self.tcName, self.tcPathKey, self.tcURL, self.tcApiUserToken, self.dpOutputPath):
            ctrl.SetMinSize(wx.Size(320, -1))
        self.Layout()
        self.GetSizer().Fit(self)
        self.SetMinSize(self.GetSize())
        ensure_dialog_fits(self, prefer=(520, -1))

        if data is None:
            self._data = {
                'name': '',
                'output_path': '',
                'path_key': '',
                'api_url': '',
                'api_version': 'v1',
                'api_user_token': '',
            }
        else:
            self._data = dict(data)
            self._data.pop('author', None)
            self.tcName.SetValue(self._data['name'])
            self.tcPathKey.SetValue(self._data['path_key'])
            self.dpOutputPath.SetPath(self._data['output_path'])
            self.tcURL.SetValue(self._data['api_url'])
            # KiCad's HTTP library protocol is v1. A numeric server version must not be written here.
            version = (self._data.get('api_version') or '').strip()
            if version.lower() in ('', '1', '2', 'v2'):
                version = 'v1'
            self._data['api_version'] = version
            self.tcApiVersion.SetValue(version)
            self.tcApiUserToken.SetValue(self._data['api_user_token'])

    def SettingsDialogButtonsOnCancelButtonClick( self, event ):
        event.Skip()

    def CaptureSettings(self):
        self._data['name'] = self.tcName.GetValue()
        self._data['path_key'] = self.tcPathKey.GetValue()
        self._data['output_path'] = self.dpOutputPath.GetPath()
        self._data['api_url'] = self.tcURL.GetValue()
        version = self.tcApiVersion.GetValue().strip() or 'v1'
        if version.lower() in ('1', '2', 'v2'):
            version = 'v1'
        self._data['api_version'] = version
        self._data['api_user_token'] = self.tcApiUserToken.GetValue()
        self._data.pop('author', None)
        self._accepted = True

    def SettingsDialogButtonsOnSaveButtonClick( self, event ):
        self.CaptureSettings()
        # wx.ID_SAVE is a GTK stock button: the dialog response closes the
        # window on its own and overwrites any other EndModal() code.
        if self.IsModal():
            self.EndModal(wx.ID_SAVE)

    def WasAccepted(self):
        return self._accepted

    def GetSettingsData(self):
        return self._data


class ChangeReviewDialog(wx.Dialog):
    """Per-file decision after a scan: apply, ignore, or revert."""

    _CHOICES = ["Apply", "Ignore", "Revert"]
    _VALUES = ["apply", "ignore", "revert"]

    def __init__(self, parent, rows):
        wx.Dialog.__init__(
            self, parent, title="Review changes",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._rows = rows
        self._updating = False

        sizer = wx.BoxSizer(wx.VERTICAL)
        help_text = wx.StaticText(
            self,
            label=(
                "Choose what happens to each file. "
                "Apply runs the planned sync. Ignore leaves the file unchanged. "
                "Revert undoes the change: local edits are discarded, and a change that exists only on the server is pushed back. "
                "Deleting a footprint, symbol, 3D model or datasheet that is still used is rejected."
            ),
        )
        help_text.Wrap(760)
        sizer.Add(help_text, 0, wx.ALL | wx.EXPAND, 8)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.AppendColumn("Category", width=140)
        self.list.AppendColumn("File", width=340)
        self.list.AppendColumn("Change", width=160)
        self.list.AppendColumn("Decision", width=90)
        for index, row in enumerate(rows):
            item = self.list.InsertItem(index, row.category)
            self.list.SetItem(item, 1, row.path)
            self.list.SetItem(item, 2, row.change)
            self.list.SetItem(item, 3, self._label(row.decision))
        sizer.Add(self.list, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        choice_row = wx.BoxSizer(wx.HORIZONTAL)
        choice_row.Add(wx.StaticText(self, label="Selected file:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.choice = wx.Choice(self, choices=self._CHOICES)
        choice_row.Add(self.choice, 0, wx.RIGHT, 12)
        for label, value in (("Apply all", "apply"), ("Ignore all", "ignore"), ("Revert all", "revert")):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda event, decision=value: self._set_all(decision))
            choice_row.Add(button, 0, wx.RIGHT, 4)
        sizer.Add(choice_row, 0, wx.ALL | wx.EXPAND, 8)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizer(sizer)
        self.SetSize((820, 540))
        ensure_dialog_fits(self, prefer=(820, 540))

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self.choice.Bind(wx.EVT_CHOICE, self._on_choice)
        if rows:
            self.list.Select(0)
            self._show_choice(0)

    def _label(self, value):
        if value in self._VALUES:
            return self._CHOICES[self._VALUES.index(value)]
        return str(value)

    def _show_choice(self, index):
        self._updating = True
        try:
            value = self._rows[index].decision
            self.choice.SetSelection(self._VALUES.index(value) if value in self._VALUES else 0)
        finally:
            self._updating = False

    def _on_select(self, event):
        self._show_choice(event.GetIndex())

    def _on_choice(self, event):
        if self._updating:
            return
        index = self.list.GetFirstSelected()
        if index < 0:
            return
        value = self._VALUES[self.choice.GetSelection()]
        self._rows[index].decision = value
        self.list.SetItem(index, 3, self._label(value))

    def _on_activate(self, event):
        index = event.GetIndex()
        current = self._rows[index].decision
        if current not in self._VALUES:
            current = "apply"
        nxt = self._VALUES[(self._VALUES.index(current) + 1) % len(self._VALUES)]
        self._rows[index].decision = nxt
        self.list.SetItem(index, 3, self._label(nxt))
        if self.list.GetFirstSelected() == index:
            self._show_choice(index)

    def _set_all(self, value):
        for index, row in enumerate(self._rows):
            row.decision = value
            self.list.SetItem(index, 3, self._label(value))
        selected = self.list.GetFirstSelected()
        if selected >= 0:
            self._show_choice(selected)


class CommitMessageDialog(wx.Dialog):
    """Commit message dialog for remote sync uploads."""

    def __init__(self, parent, changes_summary):
        wx.Dialog.__init__(
            self, parent, title="Commit changes",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._result = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Changes to upload:"), 0, wx.ALL, 5)
        self.lbChanges = wx.ListBox(self, choices=list(changes_summary or []), style=wx.LB_SINGLE)
        self.lbChanges.Enable(False)
        sizer.Add(self.lbChanges, 1, wx.ALL | wx.EXPAND, 5)

        sizer.Add(wx.StaticText(self, label="Commit message (required):"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.tcMessage = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 100))
        sizer.Add(self.tcMessage, 0, wx.ALL | wx.EXPAND, 5)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 5)

        self.SetSizer(sizer)
        self.Fit()
        ensure_dialog_fits(self, prefer=(420, 320))

        self.Bind(wx.EVT_BUTTON, self._onOk, id=wx.ID_OK)

    def _onOk(self, event):
        message = self.tcMessage.GetValue().strip()
        if not message:
            wx.MessageBox("Commit message is required.", "Commit", wx.OK | wx.ICON_WARNING, self)
            return
        self._result = message
        self.EndModal(wx.ID_OK)

    def GetResult(self):
        return self._result


if __name__ == '__main__':
    print("Starting KiPart Client...")
    app = wx.App(False)
    plg = KiPart()
    plg.defaults()
    plg.Run()
    app.MainLoop()
