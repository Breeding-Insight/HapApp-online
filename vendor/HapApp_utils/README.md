For building microhaplotype databases from targeted genotyping platforms

We developed a systematic workflow to process MADC reports and assign standardized microhaplotype IDs. The process begins with updating marker IDs to the standard “chromosomeN_000000000” format from the initial MADC report. As an initial quality control, we filter RefMatch and AltMatch sequences to require a minimum presence of either 10 samples or 5% of the total samples in a project (whichever is smaller), with each sample having at least two reads.
