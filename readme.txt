
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

These steps were validated on Linux x86_64 with the software X11 renderer
and the OpenAL sound backend.

The Makefile detects the architecture with uname -m, so the build output
goes to debug<arch>/ and release<arch>/, and the game module is named
game<arch>.so. On a 64 bit machine that is debugx86_64/, releasex86_64/
and gamex86_64.so, which is what the commands below use. On a 32 bit
machine replace x86_64 with i386.


1) Install build dependencies

	 Option A (Nix, recommended): the flake declares every dependency.

		 nix develop

	 Option B (Debian/Ubuntu-like distros):

		 sudo apt update
		 sudo apt install -y build-essential pkg-config gdb \
			 libx11-dev libxext-dev libsdl2-dev libopenal-dev

		 SDL2_sound is also required (music decoding). If your distro does
		 not package it, build it from https://github.com/icculus/SDL_sound
		 and make sure "pkg-config --cflags SDL2_sound" finds it.


2) Clone and build

	 git clone git@github.com:luizhmmachado/Quake-2.git
	 cd Quake-2
	 git checkout dev

	 Build debug:
	 make -f linux/Makefile.i386 build_debug

	 Build release:
	 make -f linux/Makefile.i386 build_release

	 Note: despite the name, linux/Makefile.i386 builds for the current
	 architecture.


3) Configure renderer library path (required by this codebase)

	 /etc/quake2.conf must hold the absolute path of the build directory.
	 Run from the repository root, so $(pwd) expands to the real path:

	 For debug build:
	 sudo sh -c "echo $(pwd)/debugx86_64 > /etc/quake2.conf"

	 For release build:
	 sudo sh -c "echo $(pwd)/releasex86_64 > /etc/quake2.conf"

	 Check it with: cat /etc/quake2.conf


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
	 cp -f debugx86_64/gamex86_64.so baseq2/gamex86_64.so

	 If you built release:
	 cp -f releasex86_64/gamex86_64.so baseq2/gamex86_64.so

	 Note: do this again after rebuilding if game code changed.


6) Music (optional)

	 The CD player was replaced by music files. Put the soundtrack in
	 baseq2/music/ (or inside a pak), named after the original CD track
	 number, in one of these formats:

		 music/02.ogg   or   music/track02.ogg
		 (.ogg, .mp3, .flac and .wav are accepted)

	 Without these files the game runs normally, only without music.


7) Run (larger window, software renderer)

	 Debug binary:
	 ./debugx86_64/quake2 \
		 +set vid_ref softx \
		 +set sw_mode 6 \
		 +set vid_fullscreen 0 \
		 +skill 1 \
		 +map demo1

	 Release binary:
	 ./releasex86_64/quake2 \
		 +set vid_ref softx \
		 +set sw_mode 6 \
		 +set vid_fullscreen 0 \
		 +skill 1 \
		 +map demo1

	 sw_mode values (common):
		 3 = 640x480
		 4 = 800x600
		 6 = 1024x768
		 8 = 1280x1024


8) Sound settings

	 Sound goes through OpenAL Soft, so it plays on whatever the system
	 uses (PipeWire, PulseAudio, ALSA). Useful console settings:

		 s_volume 0.7       effects volume (0 to 1)
		 cd_volume 1        music volume (0 to 1)
		 s_hrtf -1          3D sound for headphones: 0 = off, 1 = on, -1 = auto
		 s_device ""        OpenAL output device, empty = system default
		 s_initsound 0      start without sound
		 soundinfo          shows the OpenAL device, sample rate and HRTF state
		 cd play 2          plays music track 2 (cd stop, cd on, cd off)


9) If you rebuild renderer/game, run this sequence

	 Debug sequence:
	 make -f linux/Makefile.i386 build_debug
	 cp -f debugx86_64/gamex86_64.so baseq2/gamex86_64.so
	 ./debugx86_64/quake2 +set vid_ref softx +set sw_mode 6 +set vid_fullscreen 0 +skill 1 +map demo1

	 Release sequence:
	 make -f linux/Makefile.i386 build_release
	 cp -f releasex86_64/gamex86_64.so baseq2/gamex86_64.so
	 ./releasex86_64/quake2 +set vid_ref softx +set sw_mode 6 +set vid_fullscreen 0 +skill 1 +map demo1


Troubleshooting

- "Couldn't load pics/colormap.pcx"
	baseq2 data is missing. Ensure baseq2/pak0.pak exists.

- "failed to load game DLL"
	copy debugx86_64/gamex86_64.so to baseq2/gamex86_64.so.

- "LoadLibrary(...): can't open /etc/quake2.conf"
	create /etc/quake2.conf with the debugx86_64 absolute path (step 3).

- "LoadLibrary("ref_softx.so") failed: ... cannot open shared object file"
  followed by "Couldn't fall back to software refresh!"
	/etc/quake2.conf points to a directory that does not exist, usually
	an old debugi386 path or a placeholder that was never replaced.
	Run cat /etc/quake2.conf and redo step 3.

- "can't open OpenAL device" / no sound
	check that the system has a working output device, then run
	soundinfo in the console. To pick another device, set s_device.

- No music
	the game no longer reads a CD. Add the tracks to baseq2/music/ (step 6).

