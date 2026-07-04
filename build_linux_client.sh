#!/bin/bash

printf '\33c\e[3J'
echo ""
echo -e "\033[1m\033[37m########## \033[31mApollo\033[1;30mExplorer Linux Client - Release 1.3 \033[37m###########\033[0m\033[36m"
echo ""

echo -e "\033[1m\033[37m1. Checking Prerequisites\033[0m"
cat /etc/os-release | grep -i "debian" >log.txt 2>>log.txt
if [ $? -ne 0 ]; then
    echo -e "\033[1m\033[31mThis script is only tested on Debian-based Linux distributions (Debian, Ubuntu, etc)\033[0;30m"
    printf 'Do you want to continue anyway? (y/n):'
    read answer
    if [ "$answer" != "${answer#[Nn]}" ] ;then 
        exit 1
    fi
fi

echo -e "\033[1m\033[37m1. Clean House\033[0m"
rm -r -f .qmake.stash >log.txt 2>>log.txt
cd acp
make clean distclean >>log.txt 2>>log.txt
cd ../AmigaIconReader
make clean distclean >>log.txt 2>>log.txt
cd ../Amiga
make clean distclean >>log.txt 2>>log.txt
cd ../ApolloExplorerPC
make clean distclean >>log.txt 2>>log.txt
rm -r -f ApolloExplorer.zip >>log.txt 2>>log.txt
rm -r -f ApolloExplorer.dmg >>log.txt 2>>log.txt
cd ..

echo -e "\033[1m\033[37m2. QT6 Create Linux Project\033[0m"
qmake -recursive >>log.txt 2>>log.txt

echo -e "\033[1m\033[37m3. Make Linux Project\033[0m"
make -j16 >>log.txt 2>>log.txt

echo -e "\033[1m\033[37m4. Install Linux Project\033[0m"
sudo cp ApolloExplorerPC/ApolloExplorer /opt/ApolloExplorer/bin/ApolloExplorer
sudo cp ApolloExplorerPC/ApolloExplorer.desktop /usr/share/applications/ApolloExplorer.desktop

echo -e "\033[1m\033[37m5. Clean Project\033[0m"
cd acp
make clean >>log.txt 2>>log.txt
cd ../AmigaIconReader
make clean >>log.txt 2>>log.txt
cd ../Amiga
make clean >>log.txt 2>>log.txt
cd ../ApolloExplorerPC
make clean >>log.txt 2>>log.txt
cd ..
