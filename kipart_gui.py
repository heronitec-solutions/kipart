# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version 4.2.1-0-g80c4cb6)
## http://www.wxformbuilder.org/
##
## PLEASE DO *NOT* EDIT THIS FILE!
###########################################################################

import wx
import wx.xrc

import gettext
_ = gettext.gettext

###########################################################################
## Class KiPartGUI
###########################################################################

class KiPartGUI ( wx.Frame ):

    def __init__( self, parent ):
        wx.Frame.__init__ ( self, parent, id = wx.ID_ANY, title = wx.EmptyString, pos = wx.DefaultPosition, size = wx.Size( 900,600 ), style = wx.DEFAULT_FRAME_STYLE|wx.TAB_TRAVERSAL )

        self.SetSizeHints( wx.DefaultSize, wx.DefaultSize )

        bSizer1 = wx.BoxSizer( wx.HORIZONTAL )

        bSizer2 = wx.BoxSizer( wx.VERTICAL )

        bSizer2.SetMinSize( wx.Size( 200,-1 ) )
        lbLibListChoices = []
        self.lbLibList = wx.ListBox( self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, lbLibListChoices, 0 )
        self.lbLibList.SetFont( wx.Font( 12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, wx.EmptyString ) )

        bSizer2.Add( self.lbLibList, 1, wx.ALL|wx.EXPAND, 5 )

        bSizer4 = wx.BoxSizer( wx.HORIZONTAL )

        self.btAddLib = wx.BitmapButton( self, wx.ID_ANY, wx.NullBitmap, wx.DefaultPosition, wx.Size( 40,40 ), wx.BU_AUTODRAW|0 )

        self.btAddLib.SetBitmap( wx.NullBitmap )
        self.btAddLib.SetToolTip( _(u"Add new library") )

        bSizer4.Add( self.btAddLib, 0, wx.ALL, 5 )

        self.btDeleteLib = wx.BitmapButton( self, wx.ID_ANY, wx.NullBitmap, wx.DefaultPosition, wx.Size( 40,40 ), wx.BU_AUTODRAW|0 )

        self.btDeleteLib.SetBitmap( wx.NullBitmap )
        self.btDeleteLib.Enable( False )
        self.btDeleteLib.SetToolTip( _(u"Delete selected library") )

        bSizer4.Add( self.btDeleteLib, 0, wx.ALL, 5 )


        bSizer4.Add( ( 0, 0), 1, wx.EXPAND, 5 )

        self.btEditLib = wx.BitmapButton( self, wx.ID_ANY, wx.NullBitmap, wx.DefaultPosition, wx.Size( 40,40 ), wx.BU_AUTODRAW|0 )

        self.btEditLib.SetBitmap( wx.NullBitmap )
        self.btEditLib.Enable( False )
        self.btEditLib.SetToolTip( _(u"Edit selected library") )

        bSizer4.Add( self.btEditLib, 0, wx.ALL, 5 )


        bSizer2.Add( bSizer4, 0, wx.EXPAND, 5 )


        bSizer1.Add( bSizer2, 0, wx.EXPAND, 5 )

        bSizer6 = wx.BoxSizer( wx.VERTICAL )

        bSizer12 = wx.BoxSizer( wx.HORIZONTAL )

        self.headerImage = wx.StaticBitmap( self, wx.ID_ANY, wx.NullBitmap, wx.DefaultPosition, wx.Size( 60,60 ), 0 )
        bSizer12.Add( self.headerImage, 0, wx.ALL, 5 )

        self.lTitleText = wx.StaticText( self, wx.ID_ANY, _(u"Sync Library"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.lTitleText.Wrap( -1 )

        self.lTitleText.SetFont( wx.Font( 18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, False, wx.EmptyString ) )

        bSizer12.Add( self.lTitleText, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )


        bSizer12.Add( ( 0, 0), 1, wx.EXPAND, 5 )


        bSizer6.Add( bSizer12, 0, wx.EXPAND, 5 )

        self.m_panel3 = wx.Panel( self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.BORDER_SIMPLE|wx.TAB_TRAVERSAL )
        bSizer10 = wx.BoxSizer( wx.VERTICAL )

        bSizer9 = wx.BoxSizer( wx.HORIZONTAL )

        fgSizer3 = wx.FlexGridSizer( 5, 2, 0, 0 )
        fgSizer3.SetFlexibleDirection( wx.BOTH )
        fgSizer3.SetNonFlexibleGrowMode( wx.FLEX_GROWMODE_SPECIFIED )

        fgSizer3.SetMinSize( wx.Size( 200,-1 ) )
        self.m_staticText9 = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"New"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText9.Wrap( -1 )

        fgSizer3.Add( self.m_staticText9, 0, wx.ALL, 5 )

        self.lCntNew = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"-"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.lCntNew.Wrap( -1 )

        fgSizer3.Add( self.lCntNew, 0, wx.ALL, 5 )

        self.m_staticText11 = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"Changed"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText11.Wrap( -1 )

        fgSizer3.Add( self.m_staticText11, 0, wx.ALL, 5 )

        self.lCntChanged = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"-"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.lCntChanged.Wrap( -1 )

        fgSizer3.Add( self.lCntChanged, 0, wx.ALL, 5 )

        self.m_staticText13 = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"Deleted"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText13.Wrap( -1 )

        fgSizer3.Add( self.m_staticText13, 0, wx.ALL, 5 )

        self.lCntDeleted = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"-"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.lCntDeleted.Wrap( -1 )

        fgSizer3.Add( self.lCntDeleted, 0, wx.ALL, 5 )

        self.m_staticText15 = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"Conflict:"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText15.Wrap( -1 )

        fgSizer3.Add( self.m_staticText15, 0, wx.ALL, 5 )

        self.lCntConflict = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"-"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.lCntConflict.Wrap( -1 )

        fgSizer3.Add( self.lCntConflict, 0, wx.ALL, 5 )

        self.m_staticText17 = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"Unchanged:"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText17.Wrap( -1 )

        fgSizer3.Add( self.m_staticText17, 0, wx.ALL, 5 )

        self.lCntUnchanged = wx.StaticText( self.m_panel3, wx.ID_ANY, _(u"-"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.lCntUnchanged.Wrap( -1 )

        fgSizer3.Add( self.lCntUnchanged, 0, wx.ALL, 5 )


        bSizer9.Add( fgSizer3, 0, wx.ALL|wx.EXPAND, 5 )

        self.tProtocol = wx.TextCtrl( self.m_panel3, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, wx.TE_MULTILINE|wx.TE_READONLY )
        bSizer9.Add( self.tProtocol, 1, wx.ALL|wx.EXPAND, 5 )


        bSizer10.Add( bSizer9, 1, wx.ALL|wx.EXPAND, 5 )

        self.gProgress = wx.Gauge( self.m_panel3, wx.ID_ANY, 100, wx.DefaultPosition, wx.DefaultSize, wx.GA_HORIZONTAL )
        self.gProgress.SetValue( 0 )
        bSizer10.Add( self.gProgress, 0, wx.ALL|wx.EXPAND, 5 )

        self.gSubProgress = wx.Gauge( self.m_panel3, wx.ID_ANY, 100, wx.DefaultPosition, wx.DefaultSize, wx.GA_HORIZONTAL )
        self.gSubProgress.SetValue( 0 )
        bSizer10.Add( self.gSubProgress, 0, wx.ALL|wx.EXPAND, 5 )


        self.m_panel3.SetSizer( bSizer10 )
        self.m_panel3.Layout()
        bSizer10.Fit( self.m_panel3 )
        bSizer6.Add( self.m_panel3, 1, wx.EXPAND |wx.ALL, 5 )

        bSizer7 = wx.BoxSizer( wx.HORIZONTAL )

        self.btCheck = wx.Button( self, wx.ID_ANY, _(u"Check"), wx.DefaultPosition, wx.Size( 120,50 ), 0 )
        self.btCheck.Enable( False )
        self.btCheck.SetToolTip( _(u"Check for changes") )

        bSizer7.Add( self.btCheck, 0, wx.ALL, 5 )


        bSizer7.Add( ( 0, 0), 1, wx.EXPAND, 5 )

        self.btSync = wx.Button( self, wx.ID_ANY, _(u"Sync"), wx.DefaultPosition, wx.Size( 120,50 ), 0 )
        self.btSync.Enable( False )
        self.btSync.SetToolTip( _(u"Synchronize changes") )

        bSizer7.Add( self.btSync, 0, wx.ALL, 5 )


        bSizer6.Add( bSizer7, 0, wx.EXPAND, 5 )


        bSizer1.Add( bSizer6, 1, wx.EXPAND, 5 )


        self.SetSizer( bSizer1 )
        self.Layout()

        self.Centre( wx.BOTH )

        # Connect Events
        self.Bind( wx.EVT_SHOW, self.KiPartGUIOnShow )
        self.lbLibList.Bind( wx.EVT_LISTBOX, self.lbLibListOnListBox )
        self.btAddLib.Bind( wx.EVT_LEFT_UP, self.btAddLibOnLeftUp )
        self.btDeleteLib.Bind( wx.EVT_LEFT_UP, self.btDeleteLibOnLeftUp )
        self.btEditLib.Bind( wx.EVT_LEFT_UP, self.btEditLibOnLeftUp )
        self.btCheck.Bind( wx.EVT_LEFT_UP, self.btCheckOnLeftUp )
        self.btSync.Bind( wx.EVT_LEFT_UP, self.btSyncOnLeftUp )

    def __del__( self ):
        pass


    # Virtual event handlers, override them in your derived class
    def KiPartGUIOnShow( self, event ):
        event.Skip()

    def lbLibListOnListBox( self, event ):
        event.Skip()

    def btAddLibOnLeftUp( self, event ):
        event.Skip()

    def btDeleteLibOnLeftUp( self, event ):
        event.Skip()

    def btEditLibOnLeftUp( self, event ):
        event.Skip()

    def btCheckOnLeftUp( self, event ):
        event.Skip()

    def btSyncOnLeftUp( self, event ):
        event.Skip()


###########################################################################
## Class SettingsDialog
###########################################################################

class SettingsDialog ( wx.Dialog ):

    def __init__( self, parent ):
        wx.Dialog.__init__ ( self, parent, id = wx.ID_ANY, title = _(u"Edit Library Settings"), pos = wx.DefaultPosition, size = wx.DefaultSize, style = wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER )

        self.SetSizeHints( wx.DefaultSize, wx.DefaultSize )

        bSizer10 = wx.BoxSizer( wx.VERTICAL )

        bSizer11 = wx.BoxSizer( wx.VERTICAL )

        sbSizer1 = wx.StaticBoxSizer( wx.StaticBox( self, wx.ID_ANY, _(u"Library") ), wx.VERTICAL )

        fgSizer1 = wx.FlexGridSizer( 3, 2, 0, 0 )
        fgSizer1.AddGrowableCol( 1 )
        fgSizer1.SetFlexibleDirection( wx.BOTH )
        fgSizer1.SetNonFlexibleGrowMode( wx.FLEX_GROWMODE_SPECIFIED )

        self.m_staticText4 = wx.StaticText( sbSizer1.GetStaticBox(), wx.ID_ANY, _(u"Name"), wx.DefaultPosition, wx.Size( 100,-1 ), 0 )
        self.m_staticText4.Wrap( -1 )

        fgSizer1.Add( self.m_staticText4, 0, wx.ALL, 5 )

        self.tcName = wx.TextCtrl( sbSizer1.GetStaticBox(), wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
        fgSizer1.Add( self.tcName, 0, wx.ALL|wx.EXPAND, 5 )

        self.m_staticText5 = wx.StaticText( sbSizer1.GetStaticBox(), wx.ID_ANY, _(u"Path Key"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText5.Wrap( -1 )

        fgSizer1.Add( self.m_staticText5, 0, wx.ALL, 5 )

        self.tcPathKey = wx.TextCtrl( sbSizer1.GetStaticBox(), wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
        fgSizer1.Add( self.tcPathKey, 0, wx.ALL|wx.EXPAND, 5 )

        self.m_staticText6 = wx.StaticText( sbSizer1.GetStaticBox(), wx.ID_ANY, _(u"Output Path"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText6.Wrap( -1 )

        fgSizer1.Add( self.m_staticText6, 0, wx.ALL, 5 )

        self.dpOutputPath = wx.DirPickerCtrl( sbSizer1.GetStaticBox(), wx.ID_ANY, wx.EmptyString, _(u"Select a folder"), wx.DefaultPosition, wx.DefaultSize, wx.DIRP_DEFAULT_STYLE )
        fgSizer1.Add( self.dpOutputPath, 0, wx.ALL|wx.EXPAND, 5 )


        sbSizer1.Add( fgSizer1, 1, wx.ALL|wx.EXPAND, 5 )


        bSizer11.Add( sbSizer1, 0, wx.EXPAND, 5 )

        sbSizer3 = wx.StaticBoxSizer( wx.StaticBox( self, wx.ID_ANY, _(u"API") ), wx.VERTICAL )

        fgSizer2 = wx.FlexGridSizer( 3, 2, 0, 0 )
        fgSizer2.AddGrowableCol( 1 )
        fgSizer2.SetFlexibleDirection( wx.BOTH )
        fgSizer2.SetNonFlexibleGrowMode( wx.FLEX_GROWMODE_SPECIFIED )

        self.m_staticText7 = wx.StaticText( sbSizer3.GetStaticBox(), wx.ID_ANY, _(u"URL"), wx.DefaultPosition, wx.Size( 100,-1 ), 0 )
        self.m_staticText7.Wrap( -1 )

        fgSizer2.Add( self.m_staticText7, 0, wx.ALL, 5 )

        self.tcURL = wx.TextCtrl( sbSizer3.GetStaticBox(), wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
        fgSizer2.Add( self.tcURL, 0, wx.ALL|wx.EXPAND, 5 )

        self.m_staticText10 = wx.StaticText( sbSizer3.GetStaticBox(), wx.ID_ANY, _(u"Version"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText10.Wrap( -1 )

        fgSizer2.Add( self.m_staticText10, 0, wx.ALL, 5 )

        self.tcApiVersion = wx.TextCtrl( sbSizer3.GetStaticBox(), wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.Size( 50,-1 ), 0 )
        fgSizer2.Add( self.tcApiVersion, 0, wx.ALL, 5 )

        self.m_staticText11 = wx.StaticText( sbSizer3.GetStaticBox(), wx.ID_ANY, _(u"User Token"), wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText11.Wrap( -1 )

        fgSizer2.Add( self.m_staticText11, 0, wx.ALL, 5 )

        self.tcApiUserToken = wx.TextCtrl( sbSizer3.GetStaticBox(), wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.Size( -1,-1 ), 0 )
        fgSizer2.Add( self.tcApiUserToken, 0, wx.ALL|wx.EXPAND, 5 )


        sbSizer3.Add( fgSizer2, 1, wx.ALL|wx.EXPAND, 5 )


        bSizer11.Add( sbSizer3, 0, wx.EXPAND|wx.TOP, 8 )


        bSizer10.Add( bSizer11, 1, wx.ALL|wx.EXPAND, 12 )

        SettingsDialogButtons = wx.StdDialogButtonSizer()
        self.SettingsDialogButtonsSave = wx.Button( self, wx.ID_SAVE )
        SettingsDialogButtons.AddButton( self.SettingsDialogButtonsSave )
        self.SettingsDialogButtonsCancel = wx.Button( self, wx.ID_CANCEL )
        SettingsDialogButtons.AddButton( self.SettingsDialogButtonsCancel )
        SettingsDialogButtons.Realize()

        bSizer10.Add( SettingsDialogButtons, 0, wx.ALL|wx.EXPAND, 12 )


        self.SetSizer( bSizer10 )
        self.Layout()
        bSizer10.Fit( self )
        self.SetMinSize( self.GetSize() )

        self.Centre( wx.BOTH )

        # Connect Events
        self.SettingsDialogButtonsCancel.Bind( wx.EVT_BUTTON, self.SettingsDialogButtonsOnCancelButtonClick )
        self.SettingsDialogButtonsSave.Bind( wx.EVT_BUTTON, self.SettingsDialogButtonsOnSaveButtonClick )

    def __del__( self ):
        pass


    # Virtual event handlers, override them in your derived class
    def SettingsDialogButtonsOnCancelButtonClick( self, event ):
        event.Skip()

    def SettingsDialogButtonsOnSaveButtonClick( self, event ):
        event.Skip()


