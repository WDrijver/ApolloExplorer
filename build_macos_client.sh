#!/bin/bash

printf '\33c\e[3J'
echo ""
echo -e "\033[1m\033[37m########## \033[31mApollo\033[1;30mExplorer MacOS Client - Release 1.3 \033[37m###########\033[0m\033[36m"
echo ""

echo -e "\033[1m\033[37m0. Checking Prerequisites\033[0;30m"

sw_vers | grep "macOS" >log.txt 2>>log.txt
if [ $? -ne 0 ]; then
    echo -e "\033[1m\033[31mThis script can only be used on macOS\033[0;30m"
    exit 1
fi

qmake >>log.txt 2>>log.txt
if [ $? -ne 0 ]; then
    echo -e "\033[1m\033[31mQt qmake command not found\033[0;30m"
    printf 'Do you want to install Qt 6 from homebrew? (y/n):'
    read answer
    if [ "$answer" != "${answer#[Yy]}" ] ;then 
        echo -e "Installing Qt 6 from homebrew (be patient)\033[0;30m"
        brew install -qy qt@6 >>log.txt 2>>log.txt
    else 
        echo -e "Please install Qt 6 (homebrew, Qt online installer or build from source)"
        echo -e "Make sure qmake is in your \$PATH variable\033[0m"
        exit 1
    fi
fi

echo -e "\033[1m\033[37m1. Clean House\033[0m"
rm -r -f .qmake.stash >log.txt 2>>log.txt
make clean distclean >>log.txt 2>>log.txt
rm -r -f ApolloExplorer-macOS >>log.txt 2>>log.txt
cd ApolloExplorerPC
rm -r -f ApolloExplorer.zip >>log.txt 2>>log.txt
rm -r -f ApolloExplorer.dmg >>log.txt 2>>log.txt
cd ..

echo -e "\033[1m\033[37m2. Create macOS Project\033[0m\033[30m"

echo ""
printf 'Do you want to create macOS Universal bundle (Intel + Silicon)?:\n\033[1mIMPORTANT:\033[22m This requires a Qt 6 build with both x86_64 and arm64 support (y/n) '
read answer
if [ "$answer" != "${answer#[Yy]}" ] ;then
    qmake -recursive QMAKE_APPLE_DEVICE_ARCHS="x86_64 arm64" MACOSX_DEPLOYMENT_TARGET="12.7.6" >>log.txt 2>>log.txt
else 
    qmake -recursive MACOSX_DEPLOYMENT_TARGET="12.7.6" >>log.txt 2>>log.txt
fi

echo ""
echo -e "\033[1m\033[37m3. Make macOS Project\033[0m"
make -j16 >>log.txt 2>>log.txt

grep -i "error" log.txt
if [ $? -eq 0 ]; then
    echo -e "\033[1m\033[31mError(s) found in log.txt\033[0m"
    exit 1
fi

echo ""
printf '\033[0;30mProceeed with Signing, Notarization and Packaging?\nRequires Apple Developer Team-ID in ${APPLETEAMID}\nChoose No unless you understand the question (y/n)? '
read answer
if [ "$answer" != "${answer#[Yy]}" ] ;then 
    cd ApolloExplorerPC
    echo ""
    echo -e "\033[1m\033[37mA. QT Deploy MacOS with static Libs + Hardening + Signing\033[0m"
    macdeployqt ApolloExplorer.app -verbose=2 -sign-for-notarization=${APPLETEAMID} >>log.txt 2>>log.txt
    echo -e "\033[1m\033[37mB. ZIP ApolloExplorer.app Bundle (keep Symlinks intact)\033[0m"
    zip -r -y ApolloExplorer.zip ApolloExplorer.app >>log.txt 2>>log.txt
    echo -e "\033[1m\033[37mC. Notarize ApolloExplorer.app Bundle with Apple Developer ID (${APPLETEAMID})\033[0;30m\n"
    xcrun notarytool submit ApolloExplorer.zip --keychain-profile "AC_PASSWORD" --wait   
    echo ""
    echo -e "\033[1m\033[37mD. Staple ApolloExplorer.app Bundle with Notarization Ticket\033[0;30m\n"
    xcrun stapler staple ApolloExplorer.app  
    echo -e "\n\033[1m\033[37mE. Cleanup & Finish\033[0m\n"
    rm -r -f ApolloExplorer.zip
    cd ..
fi

echo ""
echo -e "\033[1m\033[37m4. Install macOS Project\033[0m"
mkdir -p ApolloExplorer-macOS
mv ApolloExplorerPC/ApolloExplorer.app ApolloExplorer-macOS/
mv acp/acp ApolloExplorer-macOS/

echo -e "\033[1m\033[37m5. Clean macOS Project\033[0m"
make distclean >>log.txt 2>>log.txt
echo -e "\033[0m"