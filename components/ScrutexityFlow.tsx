import React from "react";
import { motion } from "framer-motion";

const ScrutexityFlow = () => {
  const containerVariants = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: { staggerChildren: 0.8, delayChildren: 0.5 },
    },
  };

  const nodeVariants = {
    hidden: { opacity: 0, y: 10, filter: "blur(4px)" },
    show: {
      opacity: 1,
      y: 0,
      filter: "blur(0px)",
      transition: { duration: 0.6, ease: [0.16, 1, 0.3, 1] },
    },
  };

  const lineVariants = {
    hidden: { pathLength: 0, opacity: 0 },
    show: {
      pathLength: 1,
      opacity: 0.5,
      transition: { duration: 1, ease: "easeInOut" },
    },
  };

  const nodeStyle =
    "border-[0.5px] border-white/10 bg-[#0A0A0A] px-6 py-4 text-white text-xs font-mono tracking-widest flex flex-col items-center justify-center relative shadow-2xl backdrop-blur-md";

  return (
    <div className="w-full h-[600px] bg-[#080808] flex items-center justify-center overflow-hidden font-sans">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="relative w-[800px] h-[400px]"
      >
        <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
          <motion.path variants={lineVariants} d="M 150 200 L 280 200" stroke="#FFFFFF" strokeWidth="0.5" fill="transparent" strokeDasharray="4 4" />
          <motion.path variants={lineVariants} d="M 380 150 L 480 100" stroke="#FFFFFF" strokeWidth="0.5" fill="transparent" />
          <motion.path variants={lineVariants} d="M 380 200 L 480 200" stroke="#FFFFFF" strokeWidth="0.5" fill="transparent" />
          <motion.path variants={lineVariants} d="M 380 250 L 480 300" stroke="#FFFFFF" strokeWidth="0.5" fill="transparent" />
          <motion.path variants={lineVariants} d="M 620 200 L 700 200" stroke="#00C853" strokeWidth="1" fill="transparent" />
        </svg>

        <div className="absolute inset-0" style={{ zIndex: 10 }}>
          <motion.div variants={nodeVariants} className={`${nodeStyle} absolute top-[170px] left-[20px] w-[130px]`}>
            <span className="text-white/40 mb-1 text-[10px]">CLIENT</span>
            <span>UI Kit</span>
          </motion.div>

          <motion.div variants={nodeVariants} className={`${nodeStyle} absolute top-[170px] left-[280px] w-[100px] border-white/30`}>
            <span>FastAPI</span>
          </motion.div>

          <motion.div variants={nodeVariants} className={`${nodeStyle} absolute top-[70px] left-[480px] w-[140px]`}>
            <span>Signature</span>
          </motion.div>

          <motion.div variants={nodeVariants} className={`${nodeStyle} absolute top-[170px] left-[480px] w-[140px]`}>
            <span>Idempotency</span>
          </motion.div>

          <motion.div variants={nodeVariants} className={`${nodeStyle} absolute top-[270px] left-[480px] w-[140px]`}>
            <span>Atomic Ledger</span>
          </motion.div>

          <motion.div variants={nodeVariants} className={`${nodeStyle} absolute top-[170px] left-[700px] w-[100px] border-[#00C853]/40 bg-[#00C853]/5`}>
            <span className="text-[#00C853]">200 OK</span>
          </motion.div>
        </div>
      </motion.div>
    </div>
  );
};

export default ScrutexityFlow;
