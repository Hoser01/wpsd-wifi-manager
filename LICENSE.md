# License

Copyright (C) 2026 LZARC contributors

`ysf-bm-router` is licensed under the GNU General Public License, version 3 or
later.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or, at your option, any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see:

https://www.gnu.org/licenses/

SPDX-License-Identifier: GPL-3.0-or-later

## Acknowledgments And Third-Party Notices

Thanks to Chip Cuccio, `W0CHP`, for WPSD and the hotspot platform this project
is designed to complement:

https://wpsd.radio/

This project was inspired by YSFBMDirect by Stefano IS0EIR:

https://github.com/stefanolande/YSFBMDirect

Selected YSF FICH decoder components are vendored from YSFBMDirect /
pYSFReflector-derived code with original source headers preserved. The upstream
repository includes the GNU GPL version 3 license.

The experimental DMR-to-YSF conversion helper in
`src/ysf_bm_router/bridge/modeconv.py` is based on WPSD/MMDVM-family
`YSF2DMR/ModeConv.cpp` behavior and credits Jonathan Naylor G4KLX, Mathias
Weyland HB9FRV, Andy Uribe CA6JAU, Manuel Sanchez EA7EE, AD8DP, and others.
That source is GPL-2.0-or-later and is compatible with this project's
GPL-3.0-or-later licensing.

See [THIRD_PARTY.md](THIRD_PARTY.md) for detailed third-party code notes.
