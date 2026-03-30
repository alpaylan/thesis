# Build configuration for this thesis template
$pdf_mode = 1;
$out_dir = 'build';

# Ensure local class/style files in ./styles are discoverable.
$ENV{'TEXINPUTS'} = './styles//:' . ($ENV{'TEXINPUTS'} // '');
