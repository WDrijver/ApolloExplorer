#!/bin/bash

brew install qt

rm -r -f .qmake.stash
clear

qmake -recursive
make clean
make -j16
make clean

mkdir ApolloExplorerPC/ApolloExplorer.app/Contents/Resources
cp ApolloExplorerPC/icons/ApolloExplorer.icns ApolloExplorerPC/ApolloExplorer.app/Contents/Resources/ 

rm -r -f /Applications/ApolloExplorer.app
cp -r -f ApolloExplorerPC/ApolloExplorer.app /Applications/ApolloExplorer.app

rm -r -f .qmake.stash Makefile ApolloExplorerPC/Makefile ApolloExplorerPC/qmake_qmake_qm_files.qrc
rm -r -f acp/Makefile AmigaIconReader/Makefile 
