
This is the complete source code for Quake 2, version 3.19, buildable with
visual C++ 6.0.  The linux version should be buildable, but we haven't
tested it for the release.

The code is all licensed under the terms of the GPL (gnu public license).  
You should read the entire license, but the gist of it is that you can do 
anything you want with the code, including sell your new version.  The catch 
is that if you distribute new binary versions, you are required to make the 
entire source code available for free to everyone.

The primary intent of this release is for entertainment and educational 
purposes, but the GPL does allow commercial exploitation if you obey the 
full license.  If you want to do something commercial and you just can't bear 
to have your source changes released, we could still negotiate a separate 
license agreement (for $$$), but I would encourage you to just live with the 
GPL.

All of the Q2 data files remain copyrighted and licensed under the 
original terms, so you cannot redistribute data from the original game, but if 
you do a true total conversion, you can create a standalone game based on 
this code.

Thanks to Robert Duffy for doing the grunt work of building this release.

John Carmack
Id Software


=======================================================================
Linux quick start for this fork (singleplayer/local server)
=======================================================================

These steps were validated on Linux x86_64 with the software X11 renderer.

1) Install build dependencies

	 sudo apt update
	 sudo apt install -y build-essential libx11-dev gdb


2) Clone and build

	 git clone <your-fork-url>
	 cd Quake-2

	 Build debug:
	 make -f linux/Makefile.i386 build_debug

	 Build release:
	 make -f linux/Makefile.i386 build_release


3) Configure renderer library path (required by this codebase)

	 For debug build:
	 sudo sh -c 'echo /absolute/path/to/Quake-2/debugi386 > /etc/quake2.conf'

	 For release build:
	 sudo sh -c 'echo /absolute/path/to/Quake-2/releasei386 > /etc/quake2.conf'


4) Provide game data in baseq2

	 You need baseq2/pak0.pak. There are two common options:

	 Option A (full game data you already own):
		 Copy your original baseq2 files into this repository's baseq2 folder.

	 Option B (demo data package):
		 Use game-data-packager/quake2-demo-data, then copy files to this repo:

		 Verify whether demo data already exists on your machine:

			 ls /usr/share/games/quake2-demo/baseq2/pak0.pak

		 If this file exists, copy the demo baseq2 content:

			 cp -a /usr/share/games/quake2-demo/baseq2/* ./baseq2/

		 If this file does not exist, obtain data with one of these methods:

		 Method 1 (demo data package on Debian/Ubuntu-like distros):
			 sudo apt update
			 sudo apt install -y game-data-packager quake2
			 # example: if quake2-demo-data is available directly
			 sudo apt install -y quake2-demo-data
			 # example: generate/install data package with game-data-packager
			 game-data-packager --help | head
			 # then follow your distro's prompt/instructions to install generated quake2-demo-data

		 Method 2 (original game data you already own):
			 Copy your original Quake II baseq2 files (including pak0.pak)
			 into this repository's baseq2 directory.
			 Example copy command:
			 cp -a /path/to/your/original/Quake2/baseq2/* ./baseq2/


5) Copy the game module next to the game data

	 If you built debug:
	 cp -f debugi386/gamei386.so baseq2/gamei386.so

	 If you built release:
	 cp -f releasei386/gamei386.so baseq2/gamei386.so

	 Note: do this again after rebuilding if game code changed.


6) Run (larger window, software renderer, no legacy OSS sound)

	 Debug binary:
	 ./debugi386/quake2 \
		 +set vid_ref softx \
		 +set sw_mode 6 \
		 +set vid_fullscreen 0 \
		 +set s_initsound 0 \
		 +skill 1 \
		 +map demo1

	 Release binary:
	 ./releasei386/quake2 \
		 +set vid_ref softx \
		 +set sw_mode 6 \
		 +set vid_fullscreen 0 \
		 +set s_initsound 0 \
		 +skill 1 \
		 +map demo1

	 sw_mode values (common):
		 3 = 640x480
		 4 = 800x600
		 6 = 1024x768
		 8 = 1280x1024


7) If you rebuild renderer/game, run this sequence

	 Debug sequence:
	 make -f linux/Makefile.i386 build_debug
	 cp -f debugi386/gamei386.so baseq2/gamei386.so
	 ./debugi386/quake2 +set vid_ref softx +set sw_mode 6 +set vid_fullscreen 0 +set s_initsound 0 +skill 1 +map demo1

	 Release sequence:
	 make -f linux/Makefile.i386 build_release
	 cp -f releasei386/gamei386.so baseq2/gamei386.so
	 ./releasei386/quake2 +set vid_ref softx +set sw_mode 6 +set vid_fullscreen 0 +set s_initsound 0 +skill 1 +map demo1


Troubleshooting

- "Couldn't load pics/colormap.pcx"
	baseq2 data is missing. Ensure baseq2/pak0.pak exists.

- "failed to load game DLL"
	copy debugi386/gamei386.so to baseq2/gamei386.so.

- "LoadLibrary(...): can't open /etc/quake2.conf"
	create /etc/quake2.conf with the debugi386 absolute path.

- No sound / "/dev/dsp" errors
	This fork currently runs with legacy OSS disabled by default using:
	+set s_initsound 0


